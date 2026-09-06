# -*- coding: utf-8 -*-
"""绩效指标与仓位管理的单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch05_metrics.performance import compute_stats, max_drawdown, trade_stats  # noqa: E402
from ch06_risk.position_sizing import atr_risk, fixed_fraction, kelly  # noqa: E402


def test_max_drawdown_known_series():
    """净值 100 -> 120 -> 60 -> 90：最大回撤 = (60-120)/120 = -50%。"""
    idx = pd.date_range("2024-01-01", periods=4)
    equity = pd.Series([100.0, 120.0, 60.0, 90.0], index=idx)
    mdd, peak, trough = max_drawdown(equity)
    assert mdd == pytest.approx(-0.5)
    assert peak == idx[1] and trough == idx[2]


def test_compute_stats_basic():
    idx = pd.date_range("2024-01-01", periods=253, freq="D")  # 一年
    equity = 100_000.0 * np.power(1.001, np.arange(253))  # 每日 +0.1%
    stats = compute_stats(pd.Series(equity, index=idx), periods_per_year=252)
    assert stats["总收益率"] == pytest.approx(1.001 ** 252 - 1, rel=1e-3)
    assert stats["年化收益率(CAGR)"] == pytest.approx(1.001 ** 252 - 1, rel=1e-3)
    assert stats["最大回撤"] == pytest.approx(0.0, abs=1e-9)  # 单边上涨无回撤


def test_trade_stats_pairing():
    """买入100股@10 -> 卖出100股@12 => 一笔交易，收益率≈20%（不计费）。"""
    trades = [
        {"date": "d1", "side": "BUY", "price": 10.0, "shares": 100, "fee": 0},
        {"date": "d2", "side": "SELL", "price": 12.0, "shares": 100, "fee": 0},
    ]
    stats = trade_stats(trades)
    assert stats["交易次数"] == 1
    assert stats["胜率"] == pytest.approx(1.0)
    assert stats["盈利交易平均收益"] == pytest.approx(0.2, rel=1e-6)


def test_position_sizing():
    assert fixed_fraction(100_000, 0.2) == pytest.approx(20_000)
    # 总资金10万、单笔风险1%、日均波动1%（止损距离2%） => 仓位 = 1000/0.02 = 5万
    assert atr_risk(100_000, 0.01, 0.01) == pytest.approx(50_000)
    # 胜率0.4、盈亏比2：f = 0.4 - 0.6/2 = 0.1，半凯利 = 5%
    assert kelly(0.4, 2.0) == pytest.approx(0.05)
    with pytest.raises(ValueError):
        kelly(1.5, 2.0)  # 胜率不可能 > 100%
