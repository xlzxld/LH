# -*- coding: utf-8 -*-
"""第 6 章信号/因子函数库（code/research/signals.py）的契约测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.signals import (  # noqa: E402
    donchian_breakout_weights,
    factor_to_weights,
    mean_reversion_weights,
    momentum_weights,
    roc_factor,
    rsi_factor,
)
from research.param_scan import _fmt, _parse_ints  # noqa: E402
from research.walkforward import judge_verdict  # noqa: E402


def make_df(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    p = pd.Series(closes, index=idx)
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p, "volume": 1.0})


def test_roc_factor_prefix_and_value():
    df = make_df([100.0, 110.0, 99.0])
    roc = roc_factor(df, lookback=2)
    assert roc.iloc[:2].isna().all()       # 前 2 根数据不足
    assert abs(roc.iloc[2] - (99.0 / 100.0 - 1.0)) < 1e-12  # 第3天相对第1天跌1%


def test_rsi_all_up_is_high():
    """持续上涨时 RSI 应趋近 100。"""
    df = make_df([float(100 + i) for i in range(20)])
    rsi = rsi_factor(df, period=14)
    assert rsi.dropna().iloc[-1] > 90.0


def test_rsi_all_down_is_low():
    """持续下跌时 RSI 应趋近 0。"""
    df = make_df([float(100 - i) for i in range(20)])
    rsi = rsi_factor(df, period=14)
    assert rsi.dropna().iloc[-1] < 10.0


def test_factor_to_weights_contract():
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    factor = pd.Series([1.0, 0.2, -1.0, 0.3], index=idx)
    w = factor_to_weights(factor, upper=0.4, lower=-0.4)
    assert w.iloc[0] == 1.0       # > 0.4 -> 满仓
    assert w.iloc[2] == 0.0       # <= -0.4 -> 空仓
    assert pd.isna(w.iloc[1])     # 0.2 落在中间地带 -> 维持现状(NaN)
    assert pd.isna(w.iloc[3])     # 0.3 落在中间地带 -> 维持现状(NaN)


def test_momentum_weights_prefix_nan():
    """动量策略前 lookback 根应为 NaN（数据不足，维持现状）。"""
    df = make_df([100.0] * 10)
    w = momentum_weights(df, lookback=5)
    assert w.iloc[:5].isna().all()
    assert w.iloc[5:].notna().all()


def test_donchian_no_lookahead():
    """突破判断用的是'昨日'通道，不能用今天含自己的最高价（未来函数）。"""
    closes = [100.0, 101, 102, 103, 104, 100, 99, 98, 97, 110]  # 最后一天暴涨突破
    df = make_df(closes)
    w = donchian_breakout_weights(df, entry=3, exit_=3)
    # 第 10 天（index 9）收盘 110 突破前高，信号应在第 10 天出现=1
    assert w.iloc[9] == 1.0
    # 而突破前（index 8 之前）不因"未来大涨"提前给 1
    assert w.iloc[8] == 0.0


def test_mean_reversion_buy_on_dip():
    """价格跌破均线-k*标准差（超跌）时应给出买入信号 1。"""
    closes = [100.0] * 15 + [70.0]  # 横盘后突然暴跌，远低于下轨
    df = make_df(closes)
    w = mean_reversion_weights(df, lookback=10, k=2.0)
    assert w.iloc[-1] == 1.0


# ---------------------------------------------------------------- param_scan / walkforward

def test_parse_ints():
    assert _parse_ints("5,10,20") == [5, 10, 20]
    assert _parse_ints("5, 10, 20") == [5, 10, 20]   # 含空格
    assert _parse_ints("20") == [20]                  # 单值
    assert _parse_ints("") == []                      # 空串


def test_fmt():
    assert _fmt("总收益率", 0.1234).strip() == "12.3%"      # 百分比
    assert _fmt("夏普比率", 1.5).strip() == "1.50"          # 浮点
    assert _fmt("总收益率", float("nan")).strip() == "--"   # NaN
    assert _fmt("最大回撤", -0.05).strip() == "-5.0%"       # 负百分比


def test_judge_verdict_pass():
    msgs = judge_verdict(0.10, 0.05, 20)   # 样本外为正、交易足够
    assert any("通过" in m for m in msgs)
    assert not any("过拟合" in m for m in msgs)


def test_judge_verdict_overfit():
    msgs = judge_verdict(0.30, -0.10, 20)  # 样本内赚、样本外亏
    assert any("过拟合" in m for m in msgs)


def test_judge_verdict_few_trades():
    msgs = judge_verdict(0.10, 0.05, 3)    # 交易次数 < 5
    assert any("太少" in m for m in msgs)


def test_judge_verdict_divergence():
    msgs = judge_verdict(0.50, 0.10, 20)   # 差距 40% > 20 个百分点
    assert any("过期" in m for m in msgs)
