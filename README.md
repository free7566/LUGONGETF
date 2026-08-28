# 永久资产配置策略 · 自动更新站点

基于「双弱持币 + 纳指 40 日趋势过滤」的永久资产配置策略看板与 Wiki，数据每日开盘前自动重建并发布到 GitHub Pages。

## 站点结构
- `strategy-4asset.html` —— 策略看板（配置概况 / 当前信号 / 历年收益 / 组合净值走势）
- `wiki4a.html` —— 策略 Wiki（介绍 / 执行方法 / 执行纪律 / 心理按摩 / 详细数据附录）
- `index.html` —— 入口，自动跳转到看板

## 每日自动更新原理
站点是静态页，数据在构建时内联进 HTML。更新 = 定时任务跑以下流水线（均在 `update.yml` 中）：

```
new_strategy_backtest.py   # 华宝 UDSP + 天天基金，拉取最新日频数据 → _raw_daily.json
node gen_extra.js          # 读 _raw_daily.json → strategy_extra.json（含双弱+纳指40过滤新口径）
node _assemble4a.js        # 重建看板 strategy-4asset.html
node _assemble_wiki4a.js   # 重建 Wiki wiki4a.html
# 产物发布到 GitHub Pages
```

触发时机：北京时间 周一~周五 07:00（开盘前），由 `cron: '0 23 * * 0-4'`（UTC 周日~周四 23:00）驱动；亦可 push 到 main 或手动 dispatch 立即重建。

## 数据源
- 华宝基金 UDSP `INF_INDX_PRICE` → 480080.CNI / 480081.CNI / NDX.GI / 932259.CSI 日频全收益/点位
- 天天基金 `pingzhongdata` → 518880 / 511880 累计净值（含分红，等同全收益）

## 本地预览 / 调试
```bash
python3 -c "import new_strategy_backtest as m; m.fetch_all()"
node gen_extra.js
node _assemble4a.js
node _assemble_wiki4a.js
# 用任意静态服务器打开，例如：
python3 -m http.server 8080
```

## 发布到 GitHub Pages

本仓库已 `git init` 并提交（仅含源文件，不含构建产物与 `_raw_daily.json`）。在本机 Git Bash 中执行：

```bash
cd /e/workbuddy/2026-08-12-08-50-23/gh-pages
gh repo create permanent-asset-allocation --private --source=. --push -d "永久资产配置策略看板（每日自动更新）"
```

推送后（一次性）：
1. 进入仓库 **Settings → Pages → Source 选择 "GitHub Actions"** → Save
2. 进入 **Actions** 标签页，对刚生成的 workflow 点 **Re-run**（或等待下次定时触发）
3. 站点固定地址：`https://<你的用户名>.github.io/permanent-asset-allocation/`

> 推荐 `--private`：仓库源码（含内置的华宝 UDSP 密钥 `HJ_APP_SECRET`）不公开，但 Pages 站点本身仍可公网访问。
> 若改用 `--public`，密钥将随源码暴露；可在仓库 Settings→Secrets 设置 `HJ_APP_SECRET` 后，删除 `new_strategy_backtest.py` 中的硬编码默认值。

## 兜底方案（WorkBuddy 定时任务）

已在本环境创建 WorkBuddy 定时任务（ID `automation-1787882226577`，状态 ACTIVE），每个交易日开盘前运行同样的抓取→重建→重新部署流水线，保持 CloudStudio 分享链接（现有 `deploy4a/`）同步更新。GitHub Pages 为主、CloudStudio 为备。

## 免责声明
本站点仅供学习与辅助决策，不构成任何投资建议。回测基于全收益指数/累计净值，未完整计入费率、税收、滑点与申赎限制；历史表现不代表未来收益。
