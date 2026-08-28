# -*- coding: utf-8 -*-
"""
四资产动态配置策略 · 数据获取 + 回测 + 网页生成
================================================
全新策略：
  · 30% 仓位  成长×价值 日频轮动（国证成长100R × 国证价值100R 全收益）
  · 30% 仓位  持有纳斯达克100
  · 20% 仓位  持有 A500红利低波（全收益指数 932259.CSI）
  · 15% 仓位  持有 黄金ETF（518880）
  ·  5% 仓位  持有 货币基金（511880）
  · 每月底（每月首个交易日收盘）平衡仓位占比回目标权重

轮动规则（日频，全收益口径，阈值固定 1%）：
  收盘计算两者过去 20 个交易日涨跌幅：
    价值20日 > 成长20日 + 1%  → 次交易日全仓价值
    成长20日 > 价值20日 + 1%  → 次交易日全仓成长
    |差值| ≤ 1%             → 维持原有仓位，不调仓
  调仓：收盘出信号，次交易日执行。

数据源（沿用「三策略配置台」同一套取数方式）：
  · 华宝基金 UDSP  INF_INDX_PRICE  -> 480080.CNI / 480081.CNI / NDX.GI / 932259.CSI 日频全收益/点位
  · 天天基金 pingzhongdata        -> 518880 / 511880 累计净值（含分红，等同全收益）

产物：
  · _raw_daily.json        原始日频序列（缓存，便于复核）
  · strategy-4asset.html   自包含看板（数据内联，可离线打开）

用法：
  python new_strategy_backtest.py            # 拉数 + 回测 + 生成 html
  python new_strategy_backtest.py --no-fetch # 用缓存 _raw_daily.json 重算
"""
import json, os, re, sys, urllib.request, datetime, time

BASE = os.path.dirname(os.path.abspath(__file__))
PY = None  # 纯标准库，无需额外依赖
HJ_API = "https://app.fsfund.com/apps/cerdo/udsp-api/udsp/skill/v01/"
HJ_SECRET = os.environ.get("HJ_APP_SECRET", "C34A058E6A6433A0966B244517EBB0F7")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
RAW_CACHE = os.path.join(BASE, "_raw_daily.json")

# ----------------------------------------------------------------- 取数
def hj_call(api, params):
    req = urllib.request.Request(HJ_API + api, data=json.dumps(params, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json;charset=UTF-8", "hjAppSecret": HJ_SECRET})
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))

def fetch_udsp_daily(code, st="20130101", ed=None):
    """华宝 UDSP 日频点位（全收益口径；NDX.GI 为价格指数）"""
    ed = ed or datetime.date.today().strftime("%Y%m%d")
    j = hj_call("INF_INDX_PRICE", {"INDX_WINDCODE": code, "STDATE": st, "ENDDATE": ed})
    rows = ((j or {}).get("data") or {}).get("result") or []
    out = {}
    for x in rows:
        d = x.get("DATA_DATE")
        c = x.get("CLOSE_PRICE")
        if d and c is not None:
            try: out[int(d)] = float(c)
            except (ValueError, TypeError): pass
    return out

def fetch_em_nav_daily(code):
    """天天基金 累计净值（含分红）-> 日频全收益序列；时间戳按北京时间转 yyyymmdd"""
    u = f"https://fund.eastmoney.com/pingzhongdata/{code}.js"
    raw = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20).read().decode("utf-8")
    m = re.search(r"Data_ACWorthTrend\s*=\s*(\[\[.*?\]\]);", raw, re.S)
    arr = json.loads(m.group(1))
    out = {}
    for ts, nav in arr:
        d = (datetime.datetime.fromtimestamp(ts / 1000, tz=datetime.timezone.utc)
             + datetime.timedelta(hours=8)).strftime("%Y%m%d")
        try: out[int(d)] = float(nav)
        except (ValueError, TypeError): pass
    return out

def fetch_all(use_cache=False):
    if use_cache and os.path.exists(RAW_CACHE):
        return json.load(open(RAW_CACHE, encoding="utf-8"))
    print("拉取日频数据 ...", datetime.datetime.now().strftime("%H:%M:%S"))
    data = {
        "growth": fetch_udsp_daily("480080.CNI"),   # 国证成长100R 全收益
        "value":  fetch_udsp_daily("480081.CNI"),   # 国证价值100R 全收益
        "ndx":    fetch_udsp_daily("NDX.GI"),        # 纳斯达克100
        "a500":   fetch_udsp_daily("932259.CSI"),     # A500红利低波 全收益指数（全历史，替代 159296 ETF 短历史）
        "gold":   fetch_em_nav_daily("518880"),      # 黄金ETF
        "cash":   fetch_em_nav_daily("511880"),      # 货币基金
    }
    for k, v in data.items():
        print(f"  {k}: {len(v)} 条, {min(v)}~{max(v)}")
    json.dump(data, open(RAW_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    return data

# ----------------------------------------------------------------- 回测
def daily_returns(vals):
    return [None] + [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]

def max_drawdown(curve):
    peak = curve[0]; mdd = 0
    for v in curve:
        if v > peak: peak = v
        dd = v / peak - 1
        if dd < mdd: mdd = dd
    return mdd * 100

def stats(curve, rets):
    """curve: 净值序列(首值=initial); rets: 日收益序列(首=None)"""
    n = len(curve)
    total = curve[-1] / curve[0] - 1
    days = (len(curve) - 1)
    years = days / 252.0
    cagr = (curve[-1] / curve[0]) ** (1 / years) - 1 if years > 0 else 0
    mdd = max_drawdown(curve)
    rs = [r for r in rets if r is not None]
    mean = sum(rs) / len(rs)
    var = sum((r - mean) ** 2 for r in rs) / len(rs)
    vol = (var ** 0.5) * (252 ** 0.5) * 100
    sharpe = (cagr - 0.02) / (vol / 100) if vol > 1e-6 else 0
    # 月度收益
    monthly = []
    prev_m = None; prev_v = None
    for i, v in enumerate(curve):
        m = None
        monthly.append(v)
    return {"total": total * 100, "cagr": cagr * 100, "mdd": mdd, "vol": vol, "sharpe": sharpe}

def rotation_hold(dates, gval, vval, thr=0.01):
    """返回 hold[] : 第 t 天持仓 'growth' / 'value'
    信号在 t 日收盘算出 -> 作用于 t+1 日（次交易日执行）"""
    n = len(dates)
    hold = ["value"] * n
    for t in range(20, n):
        g20 = gval[t] / gval[t - 20] - 1
        v20 = vval[t] / vval[t - 20] - 1
        if t + 1 < n:
            if v20 > g20 + thr:
                hold[t + 1] = "value"
            elif g20 > v20 + thr:
                hold[t + 1] = "growth"
            else:
                hold[t + 1] = hold[t]
    return hold

def backtest(dates, series, weights):
    """series: dict name->daily_values(list, 与 dates 对齐); weights: dict 目标权重
    其中轮动仓(键 'rot') 的日收益由 rot_g/rot_v 按 hold[t] 决定"""
    names = list(weights.keys())
    others = [k for k in names if k != "rot"]
    n = len(dates)
    # 各非轮动仓日收益
    r = {k: daily_returns(series[k]) for k in others}
    rg = daily_returns(series["rot_g"]); rv = daily_returns(series["rot_v"])
    # 轮动持仓序列（rot 专用）
    hold = rotation_hold(dates, series["rot_g"], series["rot_v"])
    # 子账户净值（金额）
    val = {k: 1_000_000 * weights[k] for k in names}
    curve = [1_000_000]
    sub_curve = {k: [val[k]] for k in names}
    switches = []
    prev_month = dates[0][:6]
    prev_hold = hold[0]
    for t in range(1, n):
        # rot 当天收益取决于 hold[t]
        r_rot = rg[t] if hold[t] == "growth" else rv[t]
        val["rot"] *= (1 + r_rot)
        for k in others:
            val[k] *= (1 + r[k][t])
        total = sum(val.values())
        # 记录切换
        if hold[t] != prev_hold:
            g20 = series["rot_g"][t] / series["rot_g"][t - 20] - 1 if t >= 20 else None
            v20 = series["rot_v"][t] / series["rot_v"][t - 20] - 1 if t >= 20 else None
            switches.append({"d": dates[t], "from": prev_hold, "to": hold[t],
                             "g20": round(g20 * 100, 2) if g20 is not None else None,
                             "v20": round(v20 * 100, 2) if v20 is not None else None})
            prev_hold = hold[t]
        # 月度再平衡（当月首个交易日收盘后复位目标权重）
        cur_month = dates[t][:6]
        if cur_month != prev_month:
            for k in names:
                val[k] = total * weights[k]
            prev_month = cur_month
        curve.append(total)
        for k in names:
            sub_curve[k].append(val[k])
    # 组合日收益
    rets = [None] + [curve[i] / curve[i - 1] - 1 for i in range(1, n)]
    st = stats(curve, rets)
    return {"curve": curve, "sub": sub_curve, "switches": switches,
            "hold": hold, "stats": st, "rets": rets}

def pure_buyhold(dates, series, name, weight=1.0, initial=1_000_000):
    """单一标的买入持有（用于对比）"""
    v = series[name]
    curve = [initial * weight]
    for t in range(1, len(dates)):
        curve.append(curve[-1] * (v[t] / v[t - 1]))
    rets = [None] + [curve[i] / curve[i - 1] - 1 for i in range(1, len(dates))]
    return {"curve": curve, "stats": stats(curve, rets)}

# ----------------------------------------------------------------- 主流程
def build():
    use_cache = "--no-fetch" in sys.argv
    raw = fetch_all(use_cache=use_cache)

    # 对齐到共同交易日（取交集，保证所有序列都有值）
    common = set(raw["growth"].keys())
    for k in ("value", "ndx", "a500", "gold", "cash"):
        common &= set(raw[k].keys())
    common = sorted(common)
    print(f"共同交易日: {len(common)} 条 ({common[0]} ~ {common[-1]})")

    def col(k): return [raw[k][d] for d in common]
    dates = [str(d) for d in common]
    series = {
        "rot_g": col("growth"), "rot_v": col("value"),
        "ndx": col("ndx"), "a500": col("a500"),
        "gold": col("gold"), "cash": col("cash"),
    }
    weights = {"rot": 0.30, "ndx": 0.30, "a500": 0.20, "gold": 0.15, "cash": 0.05}

    bt = backtest(dates, series, weights)

    # 对比基准
    pure = {
        "纯成长100R":   pure_buyhold(dates, series, "rot_g"),
        "纯价值100R":   pure_buyhold(dates, series, "rot_v"),
        "纯纳指100":    pure_buyhold(dates, series, "ndx"),
        "纯A500红利低波": pure_buyhold(dates, series, "a500"),
        "纯黄金":       pure_buyhold(dates, series, "gold"),
        "纯货币基金":    pure_buyhold(dates, series, "cash"),
    }
    # 无轮动静态版：rot 仓位 50/50 持有成长+价值（不调仓）
    n = len(dates)
    static_curve = [1_000_000]
    w = weights
    sv_g = 1_000_000 * w["rot"] * 0.5; sv_v = 1_000_000 * w["rot"] * 0.5
    sn = 1_000_000 * w["ndx"]; sa = 1_000_000 * w["a500"]; sg = 1_000_000 * w["gold"]; sc = 1_000_000 * w["cash"]
    rg = daily_returns(series["rot_g"]); rv = daily_returns(series["rot_v"])
    rn = daily_returns(series["ndx"]); ra = daily_returns(series["a500"])
    rgold = daily_returns(series["gold"]); rcash = daily_returns(series["cash"])
    prev_month = dates[0][:6]
    for t in range(1, n):
        sv_g *= (1 + rg[t]); sv_v *= (1 + rv[t]); sn *= (1 + rn[t]); sa *= (1 + ra[t]); sg *= (1 + rgold[t]); sc *= (1 + rcash[t])
        total = sv_g + sv_v + sn + sa + sg + sc
        cur = dates[t][:6]
        if cur != prev_month:
            sv_g = total * w["rot"] * 0.5; sv_v = total * w["rot"] * 0.5
            sn = total * w["ndx"]; sa = total * w["a500"]; sg = total * w["gold"]; sc = total * w["cash"]
            prev_month = cur
        static_curve.append(total)
    static_rets = [None] + [static_curve[i] / static_curve[i - 1] - 1 for i in range(1, n)]
    pure["静态无轮动(成长+价值各半)"] = {"curve": static_curve, "stats": stats(static_curve, static_rets)}

    # 轮动仓独立长历史（仅用两只 CNI 全收益，2013+）
    long_dates = sorted(set(raw["growth"].keys()) & set(raw["value"].keys()))
    lg = [raw["growth"][d] for d in long_dates]; lv = [raw["value"][d] for d in long_dates]
    ld = [str(d) for d in long_dates]
    lhold = rotation_hold(ld, lg, lv)
    lr = [None] + [0] * (len(ld) - 1)
    cv = [1_000_000]
    for t in range(1, len(ld)):
        rr = lg[t] / lg[t - 1] - 1 if lhold[t] == "growth" else lv[t] / lv[t - 1] - 1
        cv.append(cv[-1] * (1 + rr))
    lrets = [None] + [cv[i] / cv[i - 1] - 1 for i in range(1, len(ld))]
    rot_only = {"curve": cv, "stats": stats(cv, lrets), "dates": ld, "hold": lhold,
                "gval": lg, "vval": lv}

    # 当前信号（最新一天）
    t = n - 1
    g20 = series["rot_g"][t] / series["rot_g"][t - 20] - 1
    v20 = series["rot_v"][t] / series["rot_v"][t - 20] - 1
    diff = v20 - g20
    if diff > 0.01: cur_sig = "全仓价值"
    elif -diff > 0.01: cur_sig = "全仓成长"
    else: cur_sig = "维持" + ("价值" if bt["hold"][t] == "value" else "成长")
    current = {"date": dates[t], "g20": round(g20 * 100, 2), "v20": round(v20 * 100, 2),
               "diff": round(diff * 100, 2), "hold": bt["hold"][t], "signal": cur_sig,
               "weights": weights}

    # 精简输出（避免 HTML 过大：抽稀到约 600 点）
    def thin(arr, step):
        return arr[::step] + ([arr[-1]] if len(arr) % step else [])
    step = max(1, n // 600)
    eq_dates = thin(dates, step)
    eq_curve = thin(bt["curve"], step)
    rot_dates = thin(dates, step)
    rot_hold_thin = thin(bt["hold"], step)

    DATA = {
        "meta": {
            "generated": datetime.date.today().isoformat(),
            "start": dates[0], "end": dates[-1], "n_days": n,
            "weights": weights,
            "thr": 1.0,
            "a500_note": "20% 仓用 A500红利低波全收益指数 932259.CSI（UDSP，2014-12-31 起全历史）作回测，替代 159296 ETF 的短历史；已验证该指数与 ETF 净值走势吻合（指数略高≈含股息）。",
            "sources": ["华宝 UDSP (480080.CNI/480081.CNI/NDX.GI/932259.CSI)", "天天基金 (518880/511880 累计净值)"],
        },
        "equity": {"dates": eq_dates, "curve": [round(x, 2) for x in eq_curve],
                   "weights": weights},
        "rotation": {"dates": rot_dates, "hold": rot_hold_thin,
                     "switches": bt["switches"], "hold_full": bt["hold"]},
        "stats": bt["stats"],
        "current": current,
        "comparison": {k: {"total": round(v["stats"]["total"], 2),
                          "cagr": round(v["stats"]["cagr"], 2),
                          "mdd": round(v["stats"]["mdd"], 2),
                          "sharpe": round(v["stats"]["sharpe"], 2)}
                      for k, v in pure.items()},
        "rot_only": {"dates": rot_only["dates"], "curve": rot_only["curve"],
                     "stats": rot_only["stats"], "start": rot_only["dates"][0],
                     "end": rot_only["dates"][-1]},
        "sub": {k: [round(x, 2) for x in thin(bt["sub"][k], step)] for k in bt["sub"]},
    }
    return DATA, bt, pure, rot_only

# ----------------------------------------------------------------- HTML 生成
TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>四资产动态配置策略</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
:root{--bg:#0f1115;--card:#181b22;--line:#2a2f3a;--txt:#e6e8ec;--mut:#8a93a3;--gold:#e3b341;--blue:#5b9bff;--green:#3ecf8e;--red:#ff6b6b;--purple:#b07cff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.5}
.wrap{max-width:1080px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:18px}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:18px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.kpi .v{font-size:22px;font-weight:700}
.kpi .l{font-size:12px;color:var(--mut);margin-top:2px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 12px;color:var(--mut);font-weight:600;letter-spacing:.5px}
.chart{position:relative;height:300px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}}
.sig{display:flex;flex-wrap:wrap;gap:12px;align-items:center}
.sig .box{background:#10131a;border:1px solid var(--line);border-radius:10px;padding:12px 16px;flex:1;min-width:130px}
.sig .box .v{font-size:20px;font-weight:700}
.sig .box .l{font-size:12px;color:var(--mut)}
.tag{display:inline-block;padding:2px 8px;border-radius:6px;font-size:12px;font-weight:700}
.t-grow{background:rgba(91,155,255,.15);color:var(--blue)}
.t-val{background:rgba(227,179,65,.15);color:var(--gold)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
th{color:var(--mut);font-weight:600}
.pos{color:var(--red)}.neg{color:var(--green)}
.note{font-size:12px;color:var(--mut);margin-top:8px}
.legend span{display:inline-block;font-size:12px;color:var(--mut);margin-right:14px}
.dot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:middle}
</style></head>
<body><div class="wrap">
<h1>四资产动态配置策略</h1>
<div class="sub" id="subline"></div>

<div class="kpis" id="kpis"></div>

<div class="card"><h2>组合净值走势（100 万 → 最新）</h2>
<div class="chart"><canvas id="eq"></canvas></div>
<div class="legend" style="margin-top:8px">
  <span><i class="dot" style="background:var(--gold)"></i>组合净值</span>
</div></div>

<div class="grid2">
  <div class="card"><h2>回撤（水下曲线）</h2><div class="chart"><canvas id="dd"></canvas></div></div>
  <div class="card"><h2>当前信号 · 次交易日动作</h2><div id="signal"></div>
    <div class="note" id="sigrule"></div></div>
</div>

<div class="card"><h2>30% 轮动仓：成长 / 价值 持仓轨迹</h2>
<div class="chart"><canvas id="rot"></canvas></div>
<div class="legend" style="margin-top:8px">
  <span><i class="dot" style="background:var(--blue)"></i>持有成长100R</span>
  <span><i class="dot" style="background:var(--gold)"></i>持有价值100R</span>
</div>
<div class="note" id="switchcnt"></div></div>

<div class="card"><h2>轮动调仓记录（价值↔成长）</h2>
<div style="max-height:260px;overflow:auto"><table id="swtbl">
<thead><tr><th>日期</th><th>方向</th><th>价值20日</th><th>成长20日</th></tr></thead>
<tbody></tbody></table></div></div>

<div class="card"><h2>对比：本策略 vs 各纯标的 / 无轮动</h2>
<table id="cmp"><thead><tr><th>方案</th><th>总收益%</th><th>年化%</th><th>最大回撤%</th><th>夏普</th></tr></thead>
<tbody></tbody></table>
<div class="note">对比均在相同窗口（<span id="cmpwin"></span>）内；"静态无轮动"=30%仓 50/50 持有成长+价值但不调仓，其余相同。</div></div>

<div class="card"><h2>轮动仓独立长历史（国证成长/价值100R 全收益 2013+）</h2>
<div class="chart"><canvas id="rotlong"></canvas></div>
<div class="note" id="rotlongnote"></div></div>

<div class="card"><h2>策略配置与规则</h2>
<div id="rules"></div></div>

</div>
<script>
const DATA = __DATA__;
const fmt=(x,d=2)=>(x==null?'—':Number(x).toLocaleString('zh-CN',{maximumFractionDigits:d,minimumFractionDigits:d}));
const pct=(x)=> (x>=0?'+':'')+fmt(x)+'%';
const cls=(x)=> x>=0?'pos':'neg';
// subline
document.getElementById('subline').textContent =
  `数据窗口 ${DATA.meta.start} ~ ${DATA.meta.end}（${DATA.meta.n_days} 个交易日）｜ 阈值固定 1% ｜ 生成 ${DATA.meta.generated}`;
// kpis
const s=DATA.stats;
const kpis=[['总收益',pct(s.total),cls(s.total)],
  ['年化',pct(s.cagr),cls(s.cagr)],
  ['最大回撤',pct(s.mdd),'neg'],
  ['年化波动',fmt(s.vol)+'%',''],
  ['夏普',fmt(s.sharpe),'']];
document.getElementById('kpis').innerHTML=kpis.map(k=>
  `<div class="kpi"><div class="v ${k[2]}">${k[1]}</div><div class="l">${k[0]}</div></div>`).join('');

// equity
const ctx=document.getElementById('eq').getContext('2d');
new Chart(ctx,{type:'line',data:{labels:DATA.equity.dates,datasets:[{label:'组合净值',data:DATA.equity.curve,borderColor:'#e3b341',backgroundColor:'rgba(227,179,65,.08)',fill:true,pointRadius:0,borderWidth:2}]},
  options:{plugins:{legend:{display:false}},scales:{x:{ticks:{maxTicksLimit:10,color:'#8a93a3'},grid:{color:'#2a2f3a'}},y:{ticks:{color:'#8a93a3'},grid:{color:'#2a2f3a'}}}}});

// drawdown
const eq=DATA.equity.curve; let peak=eq[0],dd=[];
for(const v of eq){if(v>peak)peak=v;dd.push((v/peak-1)*100);}
new Chart(document.getElementById('dd').getContext('2d'),{type:'line',data:{labels:DATA.equity.dates,datasets:[{label:'回撤',data:dd,borderColor:'#ff6b6b',backgroundColor:'rgba(255,107,107,.12)',fill:true,pointRadius:0,borderWidth:1.5}]},
  options:{plugins:{legend:{display:false}},scales:{x:{ticks:{maxTicksLimit:10,color:'#8a93a3'},grid:{color:'#2a2f3a'}},y:{ticks:{color:'#8a93a3'},grid:{color:'#2a2f3a'}}}}});

// signal
const c=DATA.current;
const holdTag=c.hold==='growth'?'<span class="tag t-grow">成长100R</span>':'<span class="tag t-val">价值100R</span>';
document.getElementById('signal').innerHTML=
 `<div class="sig">
   <div class="box"><div class="l">数据日期</div><div class="v">${c.date}</div></div>
   <div class="box"><div class="l">当前持仓(30%仓)</div><div class="v">${holdTag}</div></div>
   <div class="box"><div class="l">次交易日信号</div><div class="v ${c.signal.includes('价值')?'':(c.signal.includes('成长')?'':'')}">${c.signal}</div></div>
 </div>
 <div class="sig" style="margin-top:10px">
   <div class="box"><div class="l">成长100R 20日</div><div class="v ${cls(c.g20)}">${pct(c.g20)}</div></div>
   <div class="box"><div class="l">价值100R 20日</div><div class="v ${cls(c.v20)}">${pct(c.v20)}</div></div>
   <div class="box"><div class="l">差值(价值-成长)</div><div class="v ${cls(c.diff)}">${pct(c.diff)}</div></div>
 </div>`;
document.getElementById('sigrule').textContent=
 '规则：价值20日 > 成长20日+1% → 全仓价值；成长20日 > 价值20日+1% → 全仓成长；|差值|≤1% → 维持。收盘出信号，次交易日执行。';

// rotation hold
const hcol=DATA.rotation.hold.map(h=> h==='growth'?1:0);
new Chart(document.getElementById('rot').getContext('2d'),{type:'line',data:{labels:DATA.rotation.dates,datasets:[{label:'持仓',data:hcol,stepped:true,borderColor:'#b07cff',backgroundColor:'rgba(176,124,255,.08)',fill:true,pointRadius:0,borderWidth:1.5}]},
  options:{plugins:{legend:{display:false}},scales:{x:{ticks:{maxTicksLimit:10,color:'#8a93a3'},grid:{color:'#2a2f3a'}},y:{min:-0.1,max:1.1,ticks:{color:'#8a93a3',callback:v=>v>0.5?'成长100R':'价值100R'},grid:{color:'#2a2f3a'}}}}});
document.getElementById('switchcnt').textContent=
 `共 ${DATA.rotation.switches.length} 次调仓（价值↔成长）。`;

// switch table
const tb=document.querySelector('#swtbl tbody');
tb.innerHTML=DATA.rotation.switches.slice().reverse().slice(0,200).map(s=>{
  const dir=s.from==='value'?'价值→成长':'成长→价值';
  return `<tr><td>${s.d}</td><td>${dir}</td><td class="${cls(s.v20)}">${pct(s.v20)}</td><td class="${cls(s.g20)}">${pct(s.g20)}</td></tr>`;
}).join('');

// comparison
const cmp=document.getElementById('cmp').querySelector('tbody');
const rows=Object.entries(DATA.comparison).map(([k,v])=>
  `<tr><td>${k}</td><td class="${cls(v.total)}">${pct(v.total)}</td><td class="${cls(v.cagr)}">${pct(v.cagr)}</td><td class="neg">${pct(v.mdd)}</td><td>${fmt(v.sharpe)}</td></tr>`);
// 把本策略放第一行
const me=DATA.comparison;
cmp.innerHTML=`<tr style="font-weight:700"><td>本策略(轮动)</td><td class="${cls(me_total())}">${pct(DATA.stats.total)}</td><td class="${cls(DATA.stats.cagr)}">${pct(DATA.stats.cagr)}</td><td class="neg">${pct(DATA.stats.mdd)}</td><td>${fmt(DATA.stats.sharpe)}</td></tr>`+rows;
function me_total(){return DATA.stats.total;}
document.getElementById('cmpwin').textContent=`${DATA.meta.start} ~ ${DATA.meta.end}`;

// rotation long history
const rl=DATA.rot_only;
new Chart(document.getElementById('rotlong').getContext('2d'),{type:'line',data:{labels:rl.dates,datasets:[{label:'轮动仓净值(100万起)',data:rl.curve.map(x=>Math.round(x)),borderColor:'#3ecf8e',backgroundColor:'rgba(62,207,142,.06)',fill:true,pointRadius:0,borderWidth:1.5}]},
  options:{plugins:{legend:{display:false}},scales:{x:{ticks:{maxTicksLimit:10,color:'#8a93a3'},grid:{color:'#2a2f3a'}},y:{ticks:{color:'#8a93a3'},grid:{color:'#2a2f3a'}}}}});
const r=rl.stats;
document.getElementById('rotlongnote').textContent=
 `窗口 ${rl.start} ~ ${rl.end}：总收益 ${pct(r.total)}，年化 ${pct(r.cagr)}，最大回撤 ${pct(r.mdd)}，夏普 ${fmt(r.sharpe)}。注：此段用全收益指数验证轮动逻辑本身，未含其余 4 仓。`;

// rules
const w=DATA.meta.weights;
const pctw=x=>Math.round(x*100)+'%';
document.getElementById('rules').innerHTML=
 `<table><tbody>
  <tr><td>30% 仓位</td><td>成长×价值 日频轮动（国证成长100R / 国证价值100R 全收益）</td></tr>
  <tr><td>30% 仓位</td><td>持有 纳斯达克100（NDX.GI）</td></tr>
  <tr><td>20% 仓位</td><td>持有 A500红利低波（全收益指数 932259.CSI）</td></tr>
  <tr><td>15% 仓位</td><td>持有 黄金ETF（518880）</td></tr>
  <tr><td>5% 仓位</td><td>持有 货币基金（511880）</td></tr>
  <tr><td>再平衡</td><td>每月底（月度首个交易日收盘）复位至目标权重</td></tr>
  <tr><td>轮动规则</td><td>收盘算两者 20 日涨幅；价值&gt;成长+1%→全仓价值；成长&gt;价值+1%→全仓成长；|差值|≤1%→维持。次交易日执行。阈值固定 1%。</td></tr>
  <tr><td>数据来源</td><td>${DATA.meta.sources.join('；')}</td></tr>
  <tr><td>说明</td><td>${DATA.meta.a500_note}</td></tr>
 </tbody></table>`;
</script></body></html>"""

def main():
    DATA, bt, pure, rot_only = build()
    html = TEMPLATE.replace("__DATA__", json.dumps(DATA, ensure_ascii=False))
    out = os.path.join(BASE, "strategy-4asset.html")
    open(out, "w", encoding="utf-8").write(html)
    # 控制台摘要
    s = DATA["stats"]
    print("\n==== 回测结果 ====")
    print(f"窗口: {DATA['meta']['start']} ~ {DATA['meta']['end']} ({DATA['meta']['n_days']} 交易日)")
    print(f"总收益 {s['total']:.2f}%  年化 {s['cagr']:.2f}%  最大回撤 {s['mdd']:.2f}%  波动 {s['vol']:.2f}%  夏普 {s['sharpe']:.2f}")
    print(f"轮动调仓次数: {len(DATA['rotation']['switches'])}")
    print(f"当前({DATA['current']['date']}): 持仓 {DATA['current']['hold']}  信号 {DATA['current']['signal']}  (成长20日 {DATA['current']['g20']}% / 价值20日 {DATA['current']['v20']}% / 差 {DATA['current']['diff']}%)")
    print(f"轮动仓长历史({rot_only['dates'][0]}~{rot_only['dates'][-1]}): 年化 {rot_only['stats']['cagr']:.2f}% 回撤 {rot_only['stats']['mdd']:.2f}% 夏普 {rot_only['stats']['sharpe']:.2f}")
    print(f"OK -> {out}")

if __name__ == "__main__":
    main()
