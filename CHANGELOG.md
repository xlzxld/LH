# 变更日志

本项目遵循[约定式提交](https://www.conventionalcommits.org/zh-hans/)；版本号语义：
教程内容大改升次版本，bug 修复升补丁版本。

## [1.2.0] - 2026-09-07

### 第三轮优化（外部 AI 两轮优化后的全面审查修复）

#### 修复
- **fix(live_bot)**: `--stop-loss` 参数在 argparse 从未定义、main 从未传参——
  文档承诺的实盘止损实际不可用；已接线并补入口路径疫苗测试
- **fix(live_bot)**: 止损检查提前到信号 NaN 早退之前（原顺序下，K线数据不足的
  轮次持仓不查止损）
- **fix(engine/live_bot)**: 分数仓位（如目标 0.3）破坏止损锁仓契约——实盘会把
  金叉误判为空仓反向卖出；两侧语义已统一（NaN=不动，>0=持有，0=清仓）
- fix(live_bot): 缺密钥判断按 EXCHANGE_ID 读对应键；错误分类改 isinstance；
  买入成本按实际花费记账、卖出补余额差值记账；got=0 不写脏账本
- fix(engine): 启用止损但缺 low 列时友好报错；锁仓门支持分数权重
- fix(run_dual_ma): crypto_periods 补全分钟级映射（5m 年化原错 200 倍）；
  FAQ 报错提示指向正确章节
- fix(datasource): 北交所代码显式拒绝而非误判深市
- fix(monitor): 盘中推送"现价"改用实时快照（原为昨日收盘）；删除死 NaN 分支
- fix(performance): trade_stats 移除从未使用的 equity 参数
- fix(tests): 测试状态写入隔离到临时目录（曾污染真实 bot 账本导致 dry-run 误判持仓）

#### 文档
- docs: 修正 CAGR 教学例数学错误（1.1^63≈+40,400%，原文 540%）
- docs: 修正 512100 标注（中证1000ETF/.XSHG，原误写创业板ETF/.XSHE）
- docs: 清理 15+ 处章节重编号残留；回测数字补"截至"时间戳
- docs: 第 9 章新增分数仓位实盘接线说明（9.7.1）

#### 工程
- chore: git 仓库初始化并推送 GitHub；仓库级代理配置
- chore: 测试 65 → 72 个

## [1.1.0] - 2026-09-06

### 第二轮优化（另一 AI 的两轮全方位迭代）

- 新增 `code/research/` 研究模块（ROC/RSI 因子、参数扫描、Walk-Forward 验证）
- 新增 `solutions/ch00–ch13.md` 习题答案库（14 章）
- 章节扩为 14 章（新增策略研究与开发、参数优化与过拟合两章）
- 新增实盘止损（engine + live_bot，接线问题见 1.2.0）、固定比例仓位
- live_bot 补状态账本、心跳、真钱确认短语、错误分诊
- 测试扩至 65 个

## [1.0.0] - 2026-09-06

### 首版交付

- 12 章中文教程：零基础 → 数据 → 回测 → 风控 → 币安实盘（三级安全阶梯）→
  A股监测微信推送手动下单 → 聚宽平台 → 部署运维 → FAQ
- 自研 200 行教学版回测引擎（无未来函数、手续费+滑点+最低佣金建模）
- A股数据（东方财富公开接口，重试+缓存兜底）；币安数据（ccxt，大陆可直连域名）
- 币安双均线实盘机器人（dry-run → testnet → 真钱三重确认）
- A股监测机器人（金叉/新高/回撤信号 → Server酱/PushPlus/企业微信推送）
- 聚宽平台策略（粘贴即用）；11 个单元测试

## [1.2.1] - 2026-09-07

### 体检修复（AUDIT-SPEC 四靶心扫描，P2×4 + P3×7）

#### 修复
- **fix(live_bot)**: 睡眠期 Ctrl+C 被吞掉，机器人"按不住"——改 `break` 立即退出，附主循环级回归测试（B-01）
- fix(config): `get_int` 对 "60.5" 这类小数笔误打印警告，不再静默截断（C-02）
- chore: 输出编码降级失败改为吭声（原裸 except pass，R-3.1 模式）（C-03）
- chore: 自检脚本去掉重复 sys.path 插入（C-06）
- chore: testnet_check 横幅交易所名随 EXCHANGE_ID 走，不再写死"币安"（C-04）
- docs: 补"推送内容对渠道服务方可见"提示（C-05）；TODOS 记录 monitor 信号逻辑去重观察项（B-04）

#### 移除
- refactor: 删除零引用函数 `datasource.is_etf`、`config.get_list`（B-02/B-03；
  回滚 = `git revert` 本提交）
