# 模块结构与维护

所有命令在项目根目录执行。本项目采用普通Python模块结构，便于初学者逐步维护。

## 数据路径

`app.py`或调度器调用`engine.scan`，通过`data_provider.DataProvider`取得行情，由`validator.DataValidator`检验。`strategy.evaluate`计算纯规则，`risk.assess`独立计算费用与风险，最后写入SQLite。

- `config.py`：默认参数、加载校验和原子保存。个人配置在根目录config.json。
- `market.py`、`worker.py`：AKShare子进程、超时、缓存、完整日K和周K聚合。
- `sources.py`：腾讯、新浪等来源适配器、HTTP限速和有界重试。
- `data_provider.py`、`validator.py`：回退、来源元数据、新鲜度、未来数据阻止和独立双源校验。
- `strategy.py`：日周均线、突破和回踩，不调用大语言模型生成交易信号。
- `risk.py`：十进制分报价、百股数量、费用、技术失效位和净风险收益比。
- `backtest.py`：历史前缀回放、下一日入场和T+1退出。
- `engine.py`：单股错误隔离、初筛与候选确认、扫描记录和通知去重。
- `scheduler.py`：自选股交易时段5分钟槽和收盘重试。
- `universe.py`：沪深京股票名录及部分覆盖提示。
- `full_market.py`：全市场持久队列、批处理、断点恢复和任务阶段校验。
- `market_ui.py`：全市场页面及CSV导出。
- `store.py`、`locking.py`、`notify.py`：SQLite、进程锁及可选通知。
- `view.py`：重新展示旧扫描时复核年龄。
- `cli.py`：环境自检、模拟、真实接口探测和处理器入口。

## 修改建议

改策略先修改纯规则及相关测试；改行情源在sources中新增适配器并接入DataProvider，保留原始时间与上游身份。不要在请求失败时返回虚构或过期的实时数据。

日K与周K完整性、价格校验和风险预算是不同条件，不能因规则通过就跳过双源验证或未知风险。不要以调整技术失效位来凑预算。

全市场任务保存创建时参数，自选股使用当前配置。两类监控使用独立数据库和锁；修改代码后重启相应进程，现有任务的参数不会随侧栏修改自动改变。

`data/`和`.local/`均为本机目录，不进入Git。无需把行情数据库或.venv复制给其他人；由接收者安装依赖并自行请求公开数据。
