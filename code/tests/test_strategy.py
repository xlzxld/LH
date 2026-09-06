# -*- coding: utf-8 -*-
"""策略信号唯一真源 dual_ma_weights 的契约测试（此前全项目零覆盖，Eng S6-2）。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch04_backtest.strategy import (  # noqa: E402
    dual_ma_weights,
    dual_ma_weights_sized,
    sized_weights,
)


def make_df(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    p = pd.Series(closes, index=idx)
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p, "volume": 1.0})


def test_nan_prefix_contract():
    """慢线窗口未就绪的前段必须是 NaN —— 实盘机器人靠这个契约决定'不动'。"""
    df = make_df([100.0] * 10)
    w = dual_ma_weights(df, fast=3, slow=5)
    assert w.iloc[:3].isna().all()   # 第5天才有慢线（index 4），前4天 NaN
    assert w.iloc[4:].notna().all()


def test_cross_points():
    closes = [100, 100, 100, 100, 100, 100,   # 横盘
              90, 90, 90, 90,                 # 下跌
              120, 130, 140, 150]             # 强反弹 -> 金叉
    w = dual_ma_weights(make_df(closes), fast=3, slow=5)
    values = w.dropna()
    # 下跌段死叉状态=0
    assert (values.loc["2024-01-07":"2024-01-10"] == 0.0).all()
    # 反弹末端金叉状态=1
    assert w.iloc[-1] == 1.0
    # 出现过一次 0 -> 1 跳变
    diff = values.diff().dropna()
    assert (diff == 1.0).any()


def test_equal_mas_is_flat():
    """快线 == 慢线 不是金叉（严格大于才算），且不产生 NaN 以外的模糊态。"""
    closes = [100.0] * 8
    w = dual_ma_weights(make_df(closes), fast=3, slow=5)
    assert (w.dropna() == 0.0).all()


def test_sized_weights_scales_and_preserves_nan():
    """把 0/1 信号缩放到 0~fraction，NaN 保持不变。"""
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    w = pd.Series([1.0, 0.0, 1.0, float("nan")], index=idx)
    sw = sized_weights(w, 0.3)
    assert sw.iloc[0] == 0.3
    assert sw.iloc[1] == 0.0
    assert sw.iloc[2] == 0.3
    assert pd.isna(sw.iloc[3])


def test_sized_weights_validates_fraction():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    w = pd.Series([1.0, 0.0, 1.0], index=idx)
    with pytest.raises(ValueError):
        sized_weights(w, 1.5)
    with pytest.raises(ValueError):
        sized_weights(w, 0.0)


def test_dual_ma_weights_sized_last_is_fraction():
    """金叉状态的目标仓位应为 fraction（而非满仓 1.0）。"""
    closes = [100.0] * 6 + [90.0] * 4 + [120.0, 130.0, 140.0, 150.0]
    sw = dual_ma_weights_sized(make_df(closes), fast=3, slow=5, fraction=0.25)
    assert sw.iloc[-1] == 0.25


def test_crypto_periods_full_mapping():
    """年化基数必须按K线周期正确换算——5m 错按 365 算会让年化差 200 倍。"""
    from ch04_backtest.run_dual_ma import crypto_periods

    assert crypto_periods("1d") == 365
    assert crypto_periods("4h") == 365 * 6
    assert crypto_periods("1h") == 365 * 24
    assert crypto_periods("15m") == 365 * 24 * 4
    assert crypto_periods("5m") == 365 * 24 * 12
    assert crypto_periods("30m") == 365 * 24 * 2
    assert crypto_periods("1w") == 52
    assert crypto_periods("乱写") == 365  # 未知周期保守回退（并打印警告）
