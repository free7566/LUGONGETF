// 永久资产配置策略 —— 升级版派生数据生成器
// 口径：轮动仓双弱持币(20日) + 纳指40日趋势过滤，月度再平衡，权重 30/30/20/15/5
// 输出 strategy_extra.json = { DATA, EXTRA, RAW }（DATA 为页面完整数据，含 meta/stats/equity/rotation/current/comparison/rot_only）
const fs = require('fs');
const raw = JSON.parse(fs.readFileSync('_raw_daily.json', 'utf8'));

// ===== 对齐 =====
const KEYS = ['growth', 'value', 'ndx', 'a500', 'gold', 'cash'];
let common = Object.keys(raw.growth);
for (const k of KEYS.slice(1)) common = common.filter(d => d in raw[k]);
common = common.sort();
const dates = common.map(String);
const n = dates.length;
const S = {};
for (const k of KEYS) { const m = raw[k]; S[k] = common.map(d => m[d]); }

function daily_returns(v) { const r = [null]; for (let i = 1; i < v.length; i++) r.push(v[i] / v[i - 1] - 1); return r; }
const R = { g: daily_returns(S.growth), v: daily_returns(S.value), n: daily_returns(S.ndx), a: daily_returns(S.a500), gd: daily_returns(S.gold), c: daily_returns(S.cash) };

const W = { rot: 0.30, ndx: 0.30, a500: 0.20, gold: 0.15, cash: 0.05 };
const ROT_W = 20;   // 双弱持币窗口（成长&价值 20 日涨幅均<0 → 轮动仓持币）
const NDX_MA = 40;  // 纳指 40 日趋势过滤（40 日涨幅<0 → 30% 仓转货币）
const THR = 0.01;

function maxDD(curve) { let pk = curve[0], mdd = 0; for (const v of curve) { if (v > pk) pk = v; const dd = v / pk - 1; if (dd < mdd) mdd = dd; } return mdd * 100; }
function stats(curve) {
  const days = curve.length - 1, years = days / 252;
  const total = curve[curve.length - 1] / curve[0] - 1;
  const cagr = Math.pow(curve[curve.length - 1] / curve[0], 1 / years) - 1;
  const mdd = maxDD(curve);
  const rets = []; for (let i = 1; i < curve.length; i++) rets.push(curve[i] / curve[i - 1] - 1);
  const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
  const varr = rets.reduce((a, b) => a + (b - mean) ** 2, 0) / rets.length;
  const vol = Math.sqrt(varr) * Math.sqrt(252) * 100;
  return { total: total * 100, cagr: cagr * 100, mdd, vol, sharpe: vol > 1e-6 ? (cagr - 0.02) / (vol / 100) : 0 };
}

// 轮动仓信号：value/growth/cash（rotFilter 开启时双弱→cash）
function rotation_hold(g, v, thr, w, rotFilter) {
  const h = new Array(g.length).fill('value');
  for (let t = w; t < g.length; t++) {
    const g20 = g[t] / g[t - w] - 1, v20 = v[t] / v[t - w] - 1;
    if (t + 1 >= g.length) continue;
    if (rotFilter && g20 < 0 && v20 < 0) h[t + 1] = 'cash';
    else if (v20 > g20 + thr) h[t + 1] = 'value';
    else if (g20 > v20 + thr) h[t + 1] = 'growth';
    else h[t + 1] = h[t];
  }
  return h;
}

// 主引擎：月度再平衡，轮动仓按 hold（含 cash），纳指 40 日过滤
// filters: {rot: bool 双弱持币, ndx: bool 纳指40日}
function backtest(ds, SS, rr, Ww, filters) {
  const f = filters || { rot: true, ndx: true };
  const m = ds.length;
  const hold = rotation_hold(SS.growth, SS.value, THR, ROT_W, f.rot);
  const ndxMom = new Array(m).fill(0);
  if (f.ndx) for (let t = NDX_MA; t < m; t++) ndxMom[t] = SS.ndx[t] / SS.ndx[t - NDX_MA] - 1;
  const val = { rot: 1e6 * Ww.rot, ndx: 1e6 * Ww.ndx, a500: 1e6 * Ww.a500, gold: 1e6 * Ww.gold, cash: 1e6 * Ww.cash };
  const curve = [1e6];
  const sub = { rot: [val.rot], ndx: [val.ndx], a500: [val.a500], gold: [val.gold], cash: [val.cash] };
  const switches = [];
  let prevHold = hold[0];
  let curRB = ds[0].slice(0, 6);
  for (let t = 1; t < m; t++) {
    val.rot *= (1 + (hold[t] === 'growth' ? rr.g[t] : hold[t] === 'value' ? rr.v[t] : rr.c[t]));
    const rn = f.ndx ? (ndxMom[t] < 0 ? rr.c[t] : rr.n[t]) : rr.n[t];
    val.ndx *= (1 + rn);
    val.a500 *= (1 + rr.a[t]); val.gold *= (1 + rr.gd[t]); val.cash *= (1 + rr.c[t]);
    const total = val.rot + val.ndx + val.a500 + val.gold + val.cash;
    if (hold[t] !== prevHold) {
      const g20 = t >= ROT_W ? SS.growth[t] / SS.growth[t - ROT_W] - 1 : null;
      const v20 = t >= ROT_W ? SS.value[t] / SS.value[t - ROT_W] - 1 : null;
      switches.push({ d: ds[t], from: prevHold, to: hold[t], g20: g20 != null ? +(g20 * 100).toFixed(2) : null, v20: v20 != null ? +(v20 * 100).toFixed(2) : null });
      prevHold = hold[t];
    }
    const k = ds[t].slice(0, 6);
    if (k !== curRB) { val.rot = total * Ww.rot; val.ndx = total * Ww.ndx; val.a500 = total * Ww.a500; val.gold = total * Ww.gold; val.cash = total * Ww.cash; curRB = k; }
    curve.push(total);
    sub.rot.push(val.rot); sub.ndx.push(val.ndx); sub.a500.push(val.a500); sub.gold.push(val.gold); sub.cash.push(val.cash);
  }
  return { curve, sub, hold, switches, stats: stats(curve) };
}

// 静态无轮动（rot 50/50 成长+价值，月再平衡，其余同权重）——超额对比基准
function staticCurve(ds, SS, rr, Ww) {
  const m = ds.length;
  let svg = 1e6 * Ww.rot * 0.5, svv = 1e6 * Ww.rot * 0.5, sn = 1e6 * Ww.ndx, sa = 1e6 * Ww.a500, sg = 1e6 * Ww.gold, sc = 1e6 * Ww.cash;
  const c = [1e6];
  let cur = ds[0].slice(0, 6);
  for (let t = 1; t < m; t++) {
    svg *= (1 + rr.g[t]); svv *= (1 + rr.v[t]); sn *= (1 + rr.n[t]); sa *= (1 + rr.a[t]); sg *= (1 + rr.gd[t]); sc *= (1 + rr.c[t]);
    const total = svg + svv + sn + sa + sg + sc;
    const k = ds[t].slice(0, 6);
    if (k !== cur) { svg = total * Ww.rot * 0.5; svv = total * Ww.rot * 0.5; sn = total * Ww.ndx; sa = total * Ww.a500; sg = total * Ww.gold; sc = total * Ww.cash; cur = k; }
    c.push(total);
  }
  return c;
}

// 单资产买入持有曲线
function buyhold(idx, rr) {
  const m = rr[idx].length;
  const c = [1e6];
  for (let t = 1; t < m; t++) c.push(c[t - 1] * (1 + rr[idx][t]));
  return c;
}

// ===== 主回测（带过滤，新口径）=====
const bt = backtest(dates, S, R, W, { rot: true, ndx: true });
// 无过滤版（对照行 = 旧策略 V0）
const bt0 = backtest(dates, S, R, W, { rot: false, ndx: false });

// 校验（新口径应≈ 年化24.17/回撤-14.13/夏普1.77/波动12.55）
console.log('新口径校验(应≈ 年化24.17/回撤-14.13/波动12.55/夏普1.77):');
console.log('  总收益', bt.stats.total.toFixed(2), '年化', bt.stats.cagr.toFixed(2), '回撤', bt.stats.mdd.toFixed(2), '波动', bt.stats.vol.toFixed(2), '夏普', bt.stats.sharpe.toFixed(2), '轮动/切换', bt.switches.length, '持币日', bt.hold.filter(h => h === 'cash').length);
console.log('  无过滤对照:', bt0.stats.total.toFixed(2), bt0.stats.cagr.toFixed(2), bt0.stats.mdd.toFixed(2), bt0.stats.sharpe.toFixed(2), bt0.switches.length);

// ===== 单资产对比（无过滤口径一致）=====
function cmpStat(c) { const s = stats(c); return { total: +s.total.toFixed(2), cagr: +s.cagr.toFixed(2), mdd: +s.mdd.toFixed(2), sharpe: +s.sharpe.toFixed(2) }; }
const comparison = {
  '纯成长100R': cmpStat(buyhold('g', R)),
  '纯价值100R': cmpStat(buyhold('v', R)),
  '纯纳指100': cmpStat(buyhold('n', R)),
  '纯A500红利低波': cmpStat(buyhold('a', R)),
  '纯黄金': cmpStat(buyhold('gd', R)),
  '纯货币基金': cmpStat(buyhold('c', R)),
  '静态无轮动(成长+价值各半)': cmpStat(staticCurve(dates, S, R, W)),
  '本策略(无趋势过滤)': cmpStat(bt0.curve)
};

// ===== rot_only：轮动仓独立长历史（2013 起，双弱持币按货基近似=0 收益）=====
{
  const d2 = Object.keys(raw.growth).filter(d => d in raw.value && d >= '20130101').sort();
  const n2 = d2.length;
  const gg = d2.map(d => raw.growth[d]), vv = d2.map(d => raw.value[d]);
  const rg2 = daily_returns(gg), rv2 = daily_returns(vv);
  const hold2 = rotation_hold(gg, vv, THR, ROT_W, true);
  const c2 = [1e6];
  for (let t = 1; t < n2; t++) {
    const r = hold2[t] === 'growth' ? rg2[t] : hold2[t] === 'value' ? rv2[t] : 0; // 持币期近似 0 收益
    c2.push(c2[t - 1] * (1 + r));
  }
  bt.rot_only = { dates: d2, curve: c2 };
  console.log('rot_only:', d2[0], '~', d2[n2 - 1], n2, '天，终值', (c2[n2 - 1] / 1e6).toFixed(2), '倍');
}

// ===== 单次轮动统计（含持币切换）=====
{
  const sw = bt.switches, d2i = {}; dates.forEach((d, i) => d2i[d] = i);
  const assetR = { growth: R.g, value: R.v, cash: R.c };
  let mw = -Infinity, ml = Infinity, wins = 0, seg = 0;
  for (let i = 0; i < sw.length; i++) {
    const s = sw[i], t0 = d2i[s.d] + 1, t1 = (i + 1 < sw.length) ? d2i[sw[i + 1].d] : n - 1;
    const ar = assetR[s.to]; let f = 1;
    for (let t = t0; t <= t1; t++) f *= (1 + ar[t]);
    f -= 1; if (f > mw) mw = f; if (f < ml) ml = f; if (f > 0) wins++; seg++;
  }
  bt.switchStats = { maxWin: +(mw * 100).toFixed(2), maxLoss: +(ml * 100).toFixed(2), winRate: seg ? +(wins / seg * 100).toFixed(1) : 0, n: seg };
  console.log('switchStats:', JSON.stringify(bt.switchStats));
}

// ===== 年度 =====
function annual(curve) {
  const out = [];
  let curY = dates[0].slice(0, 4), yStart = curve[0], yPeak = curve[0], yMaxDD = 0;
  for (let i = 1; i < n; i++) {
    if (curve[i] > yPeak) yPeak = curve[i];
    const dd = curve[i] / yPeak - 1; if (dd < yMaxDD) yMaxDD = dd;
    const y = dates[i].slice(0, 4);
    if (y !== curY) {
      out.push({ y: curY, ret: +((curve[i - 1] / yStart - 1) * 100).toFixed(2), mdd: +(yMaxDD * 100).toFixed(2) });
      curY = y; yStart = curve[i]; yPeak = curve[i]; yMaxDD = 0;
    }
  }
  out.push({ y: curY, ret: +((curve[n - 1] / yStart - 1) * 100).toFixed(2), mdd: +(yMaxDD * 100).toFixed(2) });
  return out;
}

// ===== 抽稀 =====
const step = Math.max(1, Math.floor(n / 600));
const thin = a => a.filter((_, i) => i % step === 0).concat(a.length % step ? [a[a.length - 1]] : []);

// ===== 当前信号（双状态）=====
const tLast = n - 1;
const g20L = S.growth[tLast] / S.growth[tLast - ROT_W] - 1;
const v20L = S.value[tLast] / S.value[tLast - ROT_W] - 1;
const ndxMomL = S.ndx[tLast] / S.ndx[tLast - NDX_MA] - 1;
const rotH = bt.hold[tLast];
const rotSignal = rotH === 'growth' ? '全仓成长' : rotH === 'value' ? '全仓价值' : '轮动仓持币';
const ndxSignal = ndxMomL < 0 ? '纳指转货币' : '持有纳指';
// 持仓持续天数（轮动仓，从末端往前数连续同状态）
let holdDays = 1;
for (let i = tLast - 1; i >= 0 && bt.hold[i] === rotH; i--) holdDays++;
// 距纳指收复 40 日趋势还差涨幅
const ndxRecoverPct = ndxMomL < 0 ? +((1 / (1 + ndxMomL) - 1) * 100).toFixed(2) : 0;
const lastSwitch = bt.switches.length ? bt.switches[bt.switches.length - 1].d : null;
const current = {
  date: dates[tLast], g20: +(g20L * 100).toFixed(2), v20: +(v20L * 100).toFixed(2), diff: +((v20L - g20L) * 100).toFixed(2),
  rotHold: rotH, rotSignal, ndxSignal, ndxMom: +(ndxMomL * 100).toFixed(2),
  ndxRecoverPct, holdDays, lastSwitch, weights: W
};

// ===== DATA / EXTRA / RAW =====
const DATA = {
  meta: {
    generated: '2026-08-28', start: dates[0], end: dates[n - 1], n_days: n,
    weights: W, thr: THR * 100,
    a500_note: '20% 仓用 A500红利低波全收益指数 932259.CSI（UDSP，2014-12-31 起全历史）作回测，替代 159296 ETF 的短历史；已验证该指数与 ETF 净值走势吻合（指数略高≈含股息）。',
    sources: ['华宝 UDSP (480080.CNI/480081.CNI/NDX.GI/932259.CSI)', '天天基金 (518880/511880 累计净值)'],
    filters: {
      rot: '轮动仓双弱持币：国证成长/价值100R 的 20 日涨幅同时为负时，轮动仓(30%)持币(货币基金)，弱市不接飞刀；任一侧转正后恢复正常轮动。',
      ndx: '纳指 40 日趋势过滤：纳斯达克100 的 40 日涨幅为负时，纳指仓(30%)全部转持货币，收复 40 日趋势后回补。'
    }
  },
  stats: { total: +bt.stats.total.toFixed(2), cagr: +bt.stats.cagr.toFixed(2), mdd: +bt.stats.mdd.toFixed(2), vol: +bt.stats.vol.toFixed(2), sharpe: +bt.stats.sharpe.toFixed(3) },
  equity: { dates: thin(dates), curve: thin(bt.curve).map(x => +x.toFixed(2)) },
  rotation: { dates: thin(dates), hold: thin(bt.hold), switches: bt.switches, hold_full: bt.hold },
  current,
  comparison,
  rot_only: bt.rot_only
};

const EXTRA = {
  annual: annual(bt.curve),
  switchStats: bt.switchStats,
  cash: { dates: thin(dates), curve: thin(bt.sub.cash.map(x => x / bt.sub.cash[0])).map(x => +x.toFixed(4)) },
  excess: { dates: thin(dates), curve: thin(bt.curve.map((x, i) => (x / staticCurve(dates, S, R, W)[i] - 1) * 100)).map(x => +x.toFixed(2)) },
  weights: W
};

const RAW = {
  dates, growth: S.growth, value: S.value, ndx: S.ndx, a500: S.a500, gold: S.gold, cash: S.cash, weights: W
};

fs.writeFileSync('strategy_extra.json', JSON.stringify({ DATA, EXTRA, RAW }));
console.log('已写出 strategy_extra.json（DATA/EXTRA/RAW）');
console.log('年度:', JSON.stringify(EXTRA.annual));
