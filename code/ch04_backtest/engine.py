# -*- coding: utf-8 -*-
"""
一个"麻雀虽小、五脏俱全"的K线级回测引擎（教学用，零框架依赖）。

为什么自己写而不用 backtrader/vnpy？
  回测本质只有四步：读数据 -> 按K线循环 -> 信号变了就按规则成交 -> 逐日记录净值。
  自己写一遍（200 行），你才能看懂框架替你干了什么，也才不会被框架的坑坑骗。

引擎约定（务必记住，这是量化新手最常见的误区来源）：
  * 策略函数在每根 K 线的【收盘价】上计算目标仓位（0~1 的数字）。
    NaN 表示"数据不足，维持现状不动"——不是清仓信号！
  * execute_on="close"      : 信号当根收盘价成交 —— 简单，但实盘做不到，偏乐观。
  * execute_on="next_open"  : 信号在【下一根开盘价】成交 —— 接近实盘，默认推荐。
  * 成本模型：佣金比例 + 最低佣金（A股券商 5 元起收）+ 滑点比例；
    A股个股另有卖出印花税（stamp_duty_rate，2023-09 起为万分之五，只扣卖出腿；
    ETF/加密货币免印花税，保持默认 0）。

止损语义（stop_loss_pct，与第 8 章配套，默认关闭）：
  * 触发：当日最低价 low 击穿 持仓均价*(1-止损比例)（盘中触发，无前视）。
  * 执行：次日开盘价卖出（next_open 模式）——保守、可实盘复制。
  * 优先级：止损取消同一根K线上排队待执行的普通信号（先认错，再谈别的）。
  * 再入场：止损后进入"锁仓等待"状态，直到出现一次全新的 空仓→持有 跳变
    （0→1 或 0→任意正分数）才解锁。
  * 止损卖出不受 min_trade_pct 碎单过滤（认错单必须执行）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ch05_metrics.performance import compute_stats, trade_stats

VALID_EXECUTE_ON = ("close", "next_open")


@dataclass
class BacktestResult:
    """回测结果：净值曲线 + 成交流水 + 绩效指标。"""

    equity: pd.Series  # 每根K线收盘后的账户总权益（现金+持仓市值）
    trades: list[dict] = field(default_factory=list)  # 成交流水
    stats: dict = field(default_factory=dict)  # 绩效指标表
    benchmark: pd.Series | None = None  # 买入持有的对照净值


def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """校验数据格式：需要 open/close/high 列，index 为日期且升序无重复。"""
    if df.empty:
        raise ValueError("数据为空——请检查 CSV 是否损坏或接口是否返回了空结果")
    missing = {"open", "close"} - set(df.columns)
    if missing:
        raise ValueError(f"数据缺少列: {missing}，实际有: {list(df.columns)}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("数据 index 必须是 DatetimeIndex（日期）")
    if df.index.has_duplicates:
        raise ValueError("index 存在重复日期，请先去重")
    n_before = len(df)
    df = df.sort_index()
    df = df[df["close"] > 0]
    if len(df) < n_before:  # 剔除坏行必须让人知道：剔除会压缩时间轴，均线窗口名不副实
        print(f"[警告] 剔除了 {n_before - len(df)} 行非正收盘价数据（坏行会让'N日均线'变相拉长）")
    return df


def run_backtest(
    df: pd.DataFrame,
    target_weights: pd.Series,
    initial_cash: float = 100_000.0,
    commission_rate: float = 2.5e-4,
    slippage_rate: float = 5e-4,
    execute_on: str = "next_open",
    min_trade_pct: float = 0.005,
    with_benchmark: bool = True,
    min_fee: float = 0.0,
    stamp_duty_rate: float = 0.0,
    stop_loss_pct: float | None = None,
    periods_per_year: int | None = None,
) -> BacktestResult:
    """
    执行回测。

    :param df: OHLC 数据，必须含 open/close 列，DatetimeIndex 升序
    :param target_weights: 目标仓位（占账户总权益的比例，0=空仓，1=满仓），
        在每根K线收盘时点计算；NaN 表示"维持现状不动"
    :param initial_cash: 初始资金
    :param commission_rate: 佣金/手续费比例（单向）。A股ETF约 0.01%~0.03%，
        币安现货普通用户 0.1%
    :param slippage_rate: 滑点比例（买入成交价 = 信号价*(1+滑点)，卖出反之）
    :param execute_on: "close"（当根收盘成交）或 "next_open"（次根开盘成交，推荐）。
        next_open 的已知边界：最后一根K线收盘产生的信号/止损没有"下一根开盘"可成交，
        会被静默丢弃（对长回测影响可忽略，但短样本尾部要留意）
    :param min_trade_pct: 调仓金额低于总权益的这个比例就忽略（避免碎单）；
        止损卖单不受此限制
    :param min_fee: 每笔最低佣金（A股券商常见 5 元）。会参与现金护栏计算；
        币安等加密交易所无最低佣金，保持 0
    :param stamp_duty_rate: 卖出印花税比例，只对卖出金额收取（不参与最低佣金托底）。
        A股个股 0.0005（2023-09 起税率）；ETF 与加密货币免收，保持默认 0
    :param stop_loss_pct: 止损比例（如 0.05 = 从持仓均价亏 5% 触发）。None=不启用。
        启用时数据必须包含 low 列（止损按当日最低价触发）
    :param periods_per_year: 一年的K线根数（年化用）。None=自动推断
        （含周末的数据自动按 365 天计，A股按 252 交易日计）
    """
    if execute_on not in VALID_EXECUTE_ON:
        raise ValueError(f"execute_on 只能是 {VALID_EXECUTE_ON}")
    if stop_loss_pct is not None and "low" not in df.columns:
        raise ValueError("启用 stop_loss_pct 需要数据包含 low 列（止损按当日最低价触发）；"
                         "当前数据列: " + ", ".join(map(str, df.columns)))

    df = validate_ohlcv(df)
    weights = target_weights.reindex(df.index)

    cash = float(initial_cash)
    shares = 0.0
    entry_price: float | None = None  # 持仓均价（止损基准）
    armed = True  # 止损后进入 False，等新的 0→1 跳变才解锁
    pending_weight: float | None = None  # next_open 模式下排队中的普通信号
    pending_stop = False  # next_open 模式下排队中的止损单（优先级高于普通信号）
    trades: list[dict] = []
    equity_values: list[float] = []

    def _equity(price: float) -> float:
        return cash + shares * price

    def _fee(notional: float) -> float:
        return max(notional * commission_rate, min_fee)

    def _execute(target_weight: float, exec_price: float, when,
                 is_stop: bool = False) -> None:
        """把持仓调整到目标权重（在 exec_price 上成交）。is_stop=True 时不做碎单过滤。"""
        nonlocal cash, shares, entry_price
        if not exec_price or pd.isna(exec_price) or exec_price <= 0:
            return
        equity_now = _equity(exec_price)
        target_value = float(target_weight) * equity_now
        delta = target_value - shares * exec_price
        # 调仓金额太小就不动了，避免为几十块钱下碎单（止损单例外：认错必须执行）
        if not is_stop and abs(delta) < min_trade_pct * equity_now:
            return

        if delta > 0:  # ---- 买入
            buy_price = exec_price * (1.0 + slippage_rate)
            # 现金护栏：付款+手续费都不能超出现金。手续费 = max(比例, 最低佣金)，
            # 是分段函数，两段分别解出"买得起"的上限（min_fee=0 时与纯比例完全一致）
            probe = min(delta, cash)
            if min_fee > 0 and probe * commission_rate < min_fee:
                max_notional = cash - min_fee  # 费用封底为最低佣金
            else:
                max_notional = cash / (1.0 + commission_rate)  # 费用按比例
            notional = min(delta, max_notional)
            # 现金护栏二次收口(L1): min_fee 临界区里按比例解出的 notional 会被
            # 最低佣金托底反超 —— notional*rate < min_fee 但 notional+min_fee >
            # cash(如 cash=1000, rate=1%, min_fee=9.95 时曾成交 1000.05 元),
            # 用实际 fee 再钳一次, 保证现金永不为负
            notional = min(notional, cash - _fee(notional))
            if notional <= 0:
                return
            fee = _fee(notional)
            if fee > 0.2 * notional:  # 金额小到最低佣金占比过高，这笔交易不划算
                print(f"[跳过] {when.date()} 买入 {notional:,.0f} 元的手续费占比 "
                      f"{fee / notional:.0%} 过高（最低佣金 {min_fee} 元），已跳过")
                return
            bought = notional / buy_price
            # 更新持仓均价（先记旧仓贡献，再加新仓）
            if shares + bought > 1e-12:
                entry_price = ((entry_price or 0.0) * shares + buy_price * bought) / (shares + bought)
            cash -= notional + fee
            shares += bought
            trades.append({"date": when, "side": "BUY", "price": round(buy_price, 6),
                           "shares": round(bought, 6), "fee": round(fee, 2), "notional": round(notional, 2)})
        else:  # ---- 卖出
            sell_price = exec_price * (1.0 - slippage_rate)
            sold = min(-delta / sell_price, shares)  # 只能卖手里的（不做空）
            if sold <= 0:
                return
            notional = sold * sell_price
            fee = _fee(notional)
            tax = notional * stamp_duty_rate  # 印花税只扣卖出腿，不参与最低佣金托底
            cash += notional - fee - tax
            shares -= sold
            if shares <= 1e-12:  # 清仓：止损基准一并失效
                shares, entry_price = 0.0, None
            trades.append({"date": when, "side": "SELL", "price": round(sell_price, 6),
                           "shares": round(sold, 6), "fee": round(fee, 2),
                           "notional": round(notional, 2),
                           **({"tax": round(tax, 2)} if tax > 0 else {}),
                           **({"reason": "STOP"} if is_stop else {})})

    def _stop_hit(low: float) -> bool:
        """当日最低价是否击穿止损线（用盘中 low 触发，无前视）。"""
        if stop_loss_pct is None or shares <= 0 or entry_price is None:
            return False
        return low <= entry_price * (1.0 - stop_loss_pct)

    prev_w: float | None = None

    for i, (when, row) in enumerate(df.iterrows()):
        if execute_on == "next_open":
            # 1) 执行昨天的排队项：止损优先（它取消同一天的普通信号）
            if i > 0:
                if pending_stop:
                    _px = float(row["open"])
                    if _px and not pd.isna(_px) and _px > 0:
                        _execute(0.0, _px, when, is_stop=True)
                        armed = False  # 止损后锁仓，等新的 0→1 跳变
                        pending_stop = False
                    else:
                        # 开盘价非法(数据损坏)时保留止损单到下一根执行 ——
                        # 曾直接吞掉: armed/pending_stop 已被清, 持仓裸奔无警告
                        print(f"[警告] {when.date()} 开盘价非法({row['open']})，"
                              f"止损单顺延到下一根K线执行")
                elif pending_weight is not None:
                    if armed or pending_weight <= 0:
                        _execute(pending_weight, float(row["open"]), when)
                    pending_weight = None
            # 2) 收盘记净值
            equity_values.append(_equity(float(row["close"])))
            # 3) 收盘算新信号 / 检查止损触发
            w = weights.iloc[i]
            w = None if pd.isna(w) else float(w)
            if _stop_hit(float(row["low"])):
                pending_stop = True
                pending_weight = None  # 止损取消同bar待执行信号
            else:
                # 持有态信号（1.0 或任意正分数）在锁仓期一律拦截；
                # 解锁条件 = 出现 空仓→持有 的新跳变（分数仓位同样适用）
                if w is not None and w > 0 and not armed:
                    if prev_w is not None and prev_w <= 0:
                        armed = True
                        pending_weight = w
                    # prev_w 仍是持有态（状态未跳变）→ 继续等待，不入场
                else:
                    pending_weight = w
            prev_w = w
        else:  # close 模式：信号当根收盘直接成交（偏乐观，教学对比用）
            w = weights.iloc[i]
            w = None if pd.isna(w) else float(w)
            if _stop_hit(float(row["low"])):
                _execute(0.0, float(row["close"]), when, is_stop=True)
                armed = False
            elif w is not None and w > 0 and not armed:
                if prev_w is not None and prev_w <= 0:
                    armed = True
                    _execute(w, float(row["close"]), when)
            elif w is None:
                pass  # NaN=数据不足维持现状——此前会把 None 传进 _execute 直接 TypeError
            else:
                _execute(w, float(row["close"]), when)
            equity_values.append(_equity(float(row["close"])))  # 成交后记账（含费用）
            prev_w = w

    equity = pd.Series(equity_values, index=df.index, name="equity")
    benchmark = None
    if with_benchmark:
        benchmark = initial_cash * df["close"] / df["close"].iloc[0]
        benchmark.name = "buy_and_hold"

    ppy = periods_per_year if periods_per_year is not None else _infer_periods(df)
    stats = {}
    stats.update(compute_stats(equity, periods_per_year=ppy))
    stats.update(trade_stats(trades))
    return BacktestResult(equity=equity, trades=trades, stats=stats, benchmark=benchmark)


def _infer_periods(df: pd.DataFrame) -> int:
    """
    根据K线间隔推断一年有多少根K线。
    含周末的品种（加密货币 7×24）按自然年计：日线 365、小时线 8760；
    A股等只有交易日的品种按 252 计。显式传入 periods_per_year 可覆盖。
    """
    if len(df) < 3:
        return 252
    step = (df.index[1] - df.index[0]).total_seconds()
    has_weekend = any(ts.weekday() >= 5 for ts in df.index[:60])
    if step >= 20 * 3600:  # 日线级别
        return 365 if has_weekend else 252
    if step >= 3500:  # 小时线级别
        return 24 * 365 if has_weekend else 252 * 4
    return int(24 * 365 * 3600 / step)  # 更细粒度，按 7×24 粗略处理
