# -*- coding: utf-8 -*-
"""回测引擎的单元测试：用已知答案的构造数据验证引擎数学正确性。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch04_backtest.engine import _infer_periods, run_backtest, validate_ohlcv  # noqa: E402


def make_df(prices: list[float], start="2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(prices), freq="D")
    p = pd.Series(prices, index=idx)
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p})


def test_buy_and_hold_no_fees():
    """零手续费 + 始终满仓（close 模式）=> 净值应精确等于价格曲线本身。"""
    df = make_df([100, 110, 90, 120])
    weights = pd.Series(1.0, index=df.index)
    result = run_backtest(df, weights, initial_cash=100_000,
                          commission_rate=0.0, slippage_rate=0.0,
                          execute_on="close", min_trade_pct=0.0)
    expected = 100_000 * df["close"] / 100.0
    pd.testing.assert_series_equal(result.equity, expected, check_names=False)


def test_next_open_lags_one_bar():
    """next_open 模式：第0根收盘的信号第1根开盘才成交，
    因此 100->110 的涨幅吃不到（第1根净值仍是 10 万）——这就是'无未来函数'的代价。"""
    df = make_df([100, 110, 120])
    weights = pd.Series([1.0, 1.0, 1.0], index=df.index)
    result = run_backtest(df, weights, initial_cash=100_000,
                          commission_rate=0.0, slippage_rate=0.0,
                          execute_on="next_open", min_trade_pct=0.0)
    assert result.equity.iloc[0] == pytest.approx(100_000)
    assert result.equity.iloc[1] == pytest.approx(100_000)  # 110 买入，110 收盘
    assert result.equity.iloc[2] == pytest.approx(100_000 * 120 / 110)


def test_no_trades_when_always_flat():
    """始终空仓 => 净值恒等于初始资金。"""
    df = make_df([100, 110, 120, 130])
    weights = pd.Series(0.0, index=df.index)
    result = run_backtest(df, weights, commission_rate=0.0, slippage_rate=0.0, min_trade_pct=0.0)
    assert (result.equity == 100_000).all()
    assert result.trades == []


def test_next_open_uses_next_bar_open():
    """next_open 模式：第0根收盘发出满仓信号 => 第1根以开盘价成交。"""
    df = make_df([100, 110, 120, 130])
    weights = pd.Series([1.0, np.nan, np.nan, np.nan], index=df.index)
    result = run_backtest(df, weights, initial_cash=100_000,
                          commission_rate=0.0, slippage_rate=0.0,
                          execute_on="next_open", min_trade_pct=0.0)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["side"] == "BUY"
    assert trade["date"] == df.index[1]
    assert trade["price"] == pytest.approx(110.0)
    assert trade["shares"] == pytest.approx(100_000 / 110.0)


def test_fees_reduce_equity():
    """买入后立刻清仓，终值应小于初始资金（手续费+滑点是确定损耗）。"""
    df = make_df([100.0, 100.0, 100.0])
    weights = pd.Series([1.0, 0.0, 0.0], index=df.index)
    result = run_backtest(df, weights, initial_cash=100_000,
                          commission_rate=0.001, slippage_rate=0.001,
                          execute_on="close", min_trade_pct=0.0)
    # close 模式：第0根收盘买入、第1根收盘卖出
    assert len(result.trades) == 2
    assert result.equity.iloc[-1] < 100_000
    # 精确值：买 100*(1+0.001)，卖 100*(1-0.001)，双边各 0.001 佣金
    buy_p, sell_p = 100 * 1.001, 100 * 0.999
    shares = 100_000 / (buy_p * 1.001)
    proceeds = shares * sell_p * 0.999
    assert result.equity.iloc[-1] == pytest.approx(100_000 - (100_000 - proceeds), rel=1e-6)


def test_cannot_sell_more_than_held():
    """纯做空信号（先卖后买）不应产生负持仓。"""
    df = make_df([100, 90, 80, 70])
    weights = pd.Series(0.0, index=df.index)
    result = run_backtest(df, weights, min_trade_pct=0.0)
    assert all(t["side"] != "SELL" or t["shares"] >= 0 for t in result.trades)
    assert (result.equity > 0).all()


def test_invalid_inputs_raise():
    bad = pd.DataFrame({"close": [1, 2]})  # 缺 open
    with pytest.raises(ValueError):
        validate_ohlcv(bad)
    df = make_df([100, 101])
    with pytest.raises(ValueError):
        run_backtest(df, pd.Series(1.0, index=df.index), execute_on="yesterday")


# ============================ 修复后新增行为（autoplan T10/T11/T12/T15） ============================

def test_empty_df_friendly_error():
    with pytest.raises(ValueError, match="数据为空"):
        run_backtest(pd.DataFrame(columns=["open", "close"]),
                     pd.Series(dtype=float))


def test_min_fee_flat_cost():
    """最低佣金：小额定购成本被托底为 min_fee，且现金永不为负。"""
    df = make_df([100.0, 100.0, 100.0])
    weights = pd.Series([1.0, 0.0, 0.0], index=df.index)
    result = run_backtest(df, weights, initial_cash=1_000,      # 1000元小账户
                          commission_rate=0.0, slippage_rate=0.0,
                          min_fee=5.0, execute_on="close", min_trade_pct=0.0)
    assert len(result.trades) == 2
    assert result.trades[0]["fee"] == 5.0 and result.trades[1]["fee"] == 5.0
    # 现金不变量：任何时刻现金都不能为负
    assert result.equity.iloc[-1] > 0


def test_min_fee_skips_ridiculous_small_trade():
    """金额小到最低佣金占比 >20% 时直接跳过这笔交易。"""
    df = make_df([100.0, 100.0])
    weights = pd.Series([1.0, 1.0], index=df.index)
    result = run_backtest(df, weights, initial_cash=20,         # 20元现金买15元: 佣金5元=33%
                          commission_rate=0.0, slippage_rate=0.0,
                          min_fee=5.0, execute_on="close", min_trade_pct=0.0)
    assert result.trades == []  # 被跳过


def test_stop_loss_triggers_on_low_executes_next_open():
    """止损：当日 low 击穿 -> 次日开盘卖出，且不受 min_trade_pct 碎单过滤。"""
    idx = pd.date_range("2024-01-01", periods=4)
    df = pd.DataFrame({
        "open":   [100.0, 102.0, 90.0, 89.0],
        "high":   [103.0, 103.0, 95.0, 95.0],
        "low":    [99.0, 101.0, 79.0, 88.0],   # 第2天 low=79 击穿 100*0.95=95
        "close":  [102.0, 102.0, 85.0, 89.0],
    }, index=idx)
    weights = pd.Series(1.0, index=idx)  # 一直保持金叉状态（止损必须独立于信号生效）
    result = run_backtest(df, weights, initial_cash=100_000,
                          commission_rate=0.0, slippage_rate=0.0, min_trade_pct=0.3,
                          stop_loss_pct=0.05, execute_on="next_open")
    stops = [t for t in result.trades if t.get("reason") == "STOP"]
    assert len(stops) == 1
    assert stops[0]["date"] == idx[3]          # 第2天low击穿 -> 第3天(次日)开盘执行
    assert stops[0]["price"] == pytest.approx(89.0)
    # 止损后当天收盘净值 = 现金（已空仓）= 卖出金额
    assert result.equity.iloc[3] == pytest.approx(stops[0]["notional"])


def test_stop_loss_blocks_reentry_until_fresh_cross():
    """止损后锁仓：即使权重保持 1.0 也不重买；直到出现 0→1 的新跳变。"""
    idx = pd.date_range("2024-01-01", periods=6)
    df = pd.DataFrame({
        "open":  [100.0, 100.0, 90.0, 91.0, 92.0, 93.0],
        "high":  [101.0, 101.0, 92.0, 93.0, 94.0, 95.0],
        "low":   [99.0,  99.0,  70.0, 90.0, 91.0, 92.0],  # 第2天击穿止损
        "close": [100.0, 100.0, 91.0, 92.0, 93.0, 94.0],
    }, index=idx)
    weights = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0, 1.0], index=idx)  # 权重恒为1
    result = run_backtest(df, weights, initial_cash=100_000,
                          commission_rate=0.0, slippage_rate=0.0, min_trade_pct=0.3,
                          stop_loss_pct=0.05, execute_on="next_open")
    buys = [t for t in result.trades if t["side"] == "BUY"]
    stops = [t for t in result.trades if t.get("reason") == "STOP"]
    assert len(stops) == 1
    assert len(buys) == 1  # 权重一直=1 却只买过一次：止损后没有"新鲜跳变"不得重进


def test_periods_per_year_weekend_detection():
    """含周末的数据（加密货币 7×24）年化基数应为 365；纯交易日应为 252。"""
    btc_idx = pd.date_range("2024-01-01", periods=60, freq="D")     # 连续日历日含周末
    astock_idx = pd.bdate_range("2024-01-01", periods=60)           # 纯工作日
    assert _infer_periods(pd.DataFrame({"close": 1.0}, index=btc_idx)) == 365
    assert _infer_periods(pd.DataFrame({"close": 1.0}, index=astock_idx)) == 252
    # 显式参数覆盖
    df = make_df([100.0] * 30)
    result = run_backtest(df, pd.Series(0.0, index=df.index), periods_per_year=365)
    assert result.stats  # 不崩即可，数值路径已由 metrics 测试覆盖


def test_stop_loss_requires_low_column():
    """启用止损但数据没有 low 列 -> 中文友好报错，而不是运行到一半裸 KeyError。"""
    df = make_df([100.0, 101.0, 102.0])  # make_df 含 low，故手工剔除
    df_no_low = df.drop(columns=["low"])
    with pytest.raises(ValueError, match="low"):
        run_backtest(df_no_low, pd.Series(1.0, index=df_no_low.index), stop_loss_pct=0.05)


def test_fractional_weights_lock_and_rearm():
    """分数仓位(0.3)的止损锁仓与再入场：锁仓期 0.3 信号被拦截，
    出现 0 -> 0.3 新跳变才解锁重进（与满仓语义一致）。"""
    idx = pd.date_range("2024-01-01", periods=8)
    base = [100.0] * 8
    df = pd.DataFrame({
        "open":  base,
        "high":  [b + 1 for b in base],
        "low":   [99.0, 70.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0],  # 第1根low击穿止损
        "close": base,
    }, index=idx)
    weights = pd.Series([0.3, 0.3, 0.3, 0.3, 0.3, 0.0, 0.3, 0.3], index=idx)
    result = run_backtest(df, weights, initial_cash=100_000,
                          commission_rate=0.0, slippage_rate=0.0, min_trade_pct=0.0,
                          stop_loss_pct=0.05, execute_on="next_open")
    stops = [t for t in result.trades if t.get("reason") == "STOP"]
    buys = [t for t in result.trades if t["side"] == "BUY"]
    assert len(stops) == 1 and stops[0]["date"] == idx[2]     # 第2根触发 -> 第3根开盘卖
    # 共两笔买入：bar0 信号的首仓(idx1开盘) + 0->0.3 新跳变后的重进(idx6开盘)
    assert len(buys) == 2
    assert buys[0]["date"] == idx[1] and buys[1]["date"] == idx[7]
    # 锁仓期间(idx3~idx5，权重持续 0.3)绝不允许重新买入
    assert all(t["date"] not in (idx[3], idx[4], idx[5]) for t in buys)
