# -*- coding: utf-8 -*-
"""
第 11 章配套文件：聚宽（JoinQuant）双均线策略 —— 直接粘贴到聚宽编辑器即可回测。

聚宽是"网页托管"式量化平台：不用配环境，数据/回测/模拟盘全在云端。
本策略与第 4 章的本地双均线逻辑完全一致，方便你对比两边的结果。

使用步骤：
    1. 注册 https://www.joinquant.com  -> 我的策略 -> 新建策略
    2. 把本文件全部内容粘贴进策略编辑器，替换模板
    3. 回测设置：起止时间、初始资金 100000、频率"每天"
    4. 点"编译运行"或"运行回测"，查看收益/回撤/交易明细
    5. 满意后可开"模拟盘"，聚宽每天自动用实时数据跑，帮你看策略"前向表现"

聚宽策略的核心结构（每个策略都是这两个函数）：
    initialize(context)  —— 开局跑一次：设基准、手续费、要买的标的
    handle_data(context, data) —— 每个交易日盘中跑一次：算信号、下单
"""

# ============ 参数区（新手只需要改这里） ============
CODE = "510300.XSHG"  # 沪深300ETF（聚宽代码带交易所后缀：.XSHG 上海 / .XSHE 深圳）
FAST = 20             # 快线窗口
SLOW = 60             # 慢线窗口


def initialize(context):
    """开局设置：只在回测开始时执行一次。"""
    # 设定基准：业绩比较的对象（沪深300指数），影响页面上的"超额收益"曲线
    set_benchmark("000300.XSHG")
    # 动态复权模式：真实价格回测（推荐），"pre"是前复权
    set_option("use_real_price", True)
    # 手续费：ETF 万分之 2.5，最低 5 元；卖出另有千分之 1 印花税（ETF 免印花税）
    set_order_cost(
        OrderCost(open_tax=0, close_tax=0,
                  open_commission=0.00025, close_commission=0.00025,
                  min_commission=5),
        type="fund",
    )
    # 每天开盘后 5 分钟再算信号，避开集合竞价的无序波动
    run_daily(run_strategy, time="9:35")


def run_strategy(context):
    """每日策略主体：算均线 -> 决定满仓还是空仓。"""
    # 取过去 SLOW+1 个交易日的日线数据（pre_close 用真实价）
    bars = get_bars(CODE, count=SLOW + 1, unit="1d", fields=["close"],
                    include_now=False, end_dt=context.current_dt)
    closes = bars["close"]
    if len(closes) < SLOW + 1:
        return  # 数据不够，跳过

    ma_fast = closes[-FAST:].mean()
    ma_slow = closes[-SLOW:].mean()

    if ma_fast > ma_slow:
        # 目标仓位 95%（留一点现金应对费用）；已满仓时该调用不会重复下单
        order_target_value(CODE, context.portfolio.total_value * 0.95)
        log.info("金叉状态：目标满仓，MA%.1f > MA%.1f" % (ma_fast, ma_slow))
    else:
        order_target(CODE, 0)  # 卖出全部持仓
        log.info("死叉状态：清仓，MA%.1f <= MA%.1f" % (ma_fast, ma_slow))


def handle_data(context, data):
    """聚宽要求的固定函数；我们用 run_daily 调度了 run_strategy，这里留空即可。"""
    pass
