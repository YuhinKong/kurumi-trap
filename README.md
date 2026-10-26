# 股票监控 Agent
老实赚钱，很枯燥吧！久留美负责心跳加速，我们负责行情监控！A股多源行情、全市场扫描、突破/回踩筛选与风险评估——你的盯盘搭子。
Making money the honest way is boring, right? Kurumi gets your heart racing; we keep an eye on the market! Multi-source A-share quotes, market-wide screening, breakout/pullback signals, and risk assessment—your market-watching sidekick.
コツコツ稼ぐなんて、退屈でしょ！ドキドキはくるみちゃんに、相場のチェックは私たちにおまかせ！中国A株の複数ソース株価、全市場スクリーニング、ブレイクアウト・押し目候補の抽出とリスク評価——あなたの相場ウォッチ仲間。

适用于 **Windows / Python 3.13** 的中文A股监控与规则研究工具，使用 Streamlit、AKShare 和 SQLite。支持自选股监控、沪深京全市场分批扫描、突破/回踩规则及费用风控。

**不连接券商、不自动交易、不保证盈利。** 本版不依赖本地行情数据库服务，暂不支持ETF。

## 功能

- **多源行情**：AKShare/东方财富、腾讯及新浪备用；显示实际来源、行情时间、获取时间、缓存与新鲜度。
- **候选校验**：日周MA5/10/20/30、突破和回踩规则；候选必须通过独立双源价格/时间验证，盘中仅预警。
- **自选监控**：侧栏编辑代码，交易时段每5分钟扫描；默认15:20后验证完整日K。
- **全A股队列**：按交易所名录建池，分批限速、逐股保存进度、暂停续扫、失败重试及CSV导出。只有规则通过才请求快照复核。
- **风险计算**：默认1000元资金、50元风险预算、100股整数倍、费用与滑点、技术失效位和净风险收益比；未知风险保留人工核验。
- **历史研究**：K线、均线、成交量、历史信号及考虑手续费/T+1的回测；模拟模式与真实数据库分离。

## 快速开始

在项目根目录打开PowerShell，确认已安装Python 3.13：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
.\.venv\Scripts\python.exe -m monitor.cli check
.\.venv\Scripts\python.exe -m streamlit run app.py
```

也可双击以下启动器；首次缺少环境时会安装依赖，正常启动不重复下载整套依赖：

1. `1-打开股票监控.cmd`：打开网页，以终端给出的网址为准。
2. `2-启动自动监控.cmd`：启动自选股调度，保留窗口。
3. `3-检查运行环境.cmd`：检查Python、依赖、配置和数据库写入。
4. `4-运行模拟扫描.cmd`：运行独立模拟测试。
5. `5-启动全A股扫描.cmd`：处理网页已经创建的全市场任务。

初次使用可先打开侧栏“模拟测试模式”，点击“立即扫描”。切回真实模式后再获取行情。VS Code选择本目录`.venv\Scripts\python.exe`作为解释器。

## 全市场使用

侧栏选择“全A股扫描”→ 更新股票名录 → 选择范围 → 创建任务 → 启动5号窗口 → 刷新进度。建议15:20后创建收盘任务；一轮可能数小时，**不是全市场每5分钟更新**。

名录完整不代表所有股票都有足够历史或可用快照；失败、过期和数据不足会单独显示。全市场结果是逐股扫描时的历史记录，加入自选后应重新扫描确认。任务完成后不会自动每天重建；跨交易日或盘中/完整K阶段变化需新建任务。

## 配置和通知

默认参数见`config.example.json`。程序会补齐已有`config.json`的新增项；侧栏可以修改常用参数和自选股，个人配置不提交Git。

通知默认关闭，通过环境变量启用，详见`.env.example`。程序**不会自动读取.env**，不要把Webhook密钥写入源码。真实与模拟SQLite由程序在`data/`下创建，该目录不随源码发布。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

默认跳过6项真实接口测试，避免把外部网络当作单元测试依赖；显式启用：

```powershell
$env:RUN_LIVE_TESTS='1'
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:RUN_LIVE_TESTS
```

工作流使用Windows/Python 3.13执行离线测试，不自动请求真实行情、不发送通知。实际验证记录及未验证项见[验证说明](docs/VALIDATION.md)。

## 文档与目录

- [完整使用流程](docs/USAGE.md)
- [模块结构与维护](docs/ARCHITECTURE.md)
- [验证范围和已知限制](docs/VALIDATION.md)
- [上传到GitHub](docs/GITHUB_UPLOAD.md)
- [贡献说明](CONTRIBUTING.md)

```text
app.py                     中文网页入口
monitor/                   行情、策略、风控、调度及全市场队列
tests/                     隔离模拟数据和可选真实接口测试
docs/                      中文使用和维护文档
.github/workflows/         Windows/Python 3.13测试工作流
config.example.json        参数示例
.env.example               环境变量说明，不含密钥
requirements.txt           依赖范围
requirements-lock.txt      已验证环境的版本快照
```

## 使用边界

公开行情源可能断开或限流，不能保证实时性和全市场完成率；不会以旧缓存冒充实时行情。非复权历史受公司行为影响。回测未完整覆盖历史ST、财报、退市样本和盘口队列。T+1、跳空、停牌和跌停可能使止损无法成交，风险预算不是实际最大亏损保证。

关闭进程、休眠或关机后不再监控。项目不创建系统后台服务或任务计划；如需自启动，按使用文档自行设置。最终交易由用户决定。
