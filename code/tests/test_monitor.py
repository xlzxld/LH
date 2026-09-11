# -*- coding: utf-8 -*-
"""monitor_astock 的单元测试：三条规则、去重/冷却、推送成功才落状态。"""
from __future__ import annotations

import sys
from datetime import date, datetime, time as dtime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch04_backtest.strategy import dual_ma_weights  # noqa: E402
import common.config as cfg  # noqa: E402
from ch08_monitor.monitor_astock import (  # noqa: E402
    check_signals, commit, in_trading_hours, parse_watchlist, pick_new, signal_frame,
)


def make_df(closes: list[float], highs: list[float] | None = None,
            end: str = "2024-06-30") -> pd.DataFrame:
    idx = pd.date_range(end=end, periods=len(closes), freq="D")
    s = pd.Series(closes, index=idx)
    h = pd.Series(highs if highs else [c * 1.01 for c in closes], index=idx)
    return pd.DataFrame({"open": s, "high": h, "low": s * 0.99, "close": s, "volume": 1.0})


def _flat_config(monkeypatch):
    monkeypatch.setattr(cfg, "get_int", lambda k, d: {"MA_FAST": 3, "MA_SLOW": 5,
                                                      "BREAKOUT_DAYS": 5,
                                                      "DRAWDOWN_DAYS": 5}.get(k, d))
    monkeypatch.setattr(cfg, "get_float", lambda k, d: {"DRAWDOWN_PCT": 10.0}.get(k, d))


def test_golden_and_death_cross(monkeypatch):
    _flat_config(monkeypatch)
    # 先跌后涨：最后一天金叉
    closes = [120, 118, 116, 114, 112, 110, 108, 106, 104, 130]
    sigs = check_signals(make_df(closes), "510300")
    assert any(s["key"].startswith("ma_gold") for s in sigs)
    # 先涨后跌：最后一天死叉
    closes = [100, 102, 104, 106, 108, 110, 112, 114, 116, 90]
    sigs = check_signals(make_df(closes), "510300")
    assert any(s["key"].startswith("ma_dead") for s in sigs)


def test_ma_signal_same_source_as_shared_strategy(monkeypatch):
    """规则1 必须与唯一真源 dual_ma_weights 同源（TODOS #0 去重契约）。

    这是"监测信号不许和回测/实盘漂移"的护栏：任何一侧改了金叉/死叉语义，
    本用例立刻变红。
    """
    _flat_config(monkeypatch)
    cases = [
        ([120, 118, 116, 114, 112, 110, 108, 106, 104, 130], "ma_gold"),  # 末根金叉
        ([100, 102, 104, 106, 108, 110, 112, 114, 116, 90], "ma_dead"),   # 末根死叉
        ([100, 101, 102, 103, 104, 105, 106, 107, 108, 109], None),       # 状态未翻转
    ]
    for closes, expect in cases:
        df = make_df(closes)
        got = {s["key"].rsplit("_", 1)[0]
               for s in check_signals(df, "510300")
               if s["key"].startswith(("ma_gold", "ma_dead"))}
        w = dual_ma_weights(df, 3, 5)
        today, yesterday = bool(w.iloc[-1] > 0), bool(w.iloc[-2] > 0)
        derived = ("ma_gold" if (today and not yesterday)
                   else "ma_dead" if (yesterday and not today) else None)
        assert derived == expect, f"用例构造有误（真源未产生预期翻转）: {closes}"
        assert got == ({expect} if expect else set())


def test_breakout_and_drawdown(monkeypatch):
    _flat_config(monkeypatch)
    # 缓涨后放量突破前高
    closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 120]
    highs = [c + 1 for c in closes]
    sigs = check_signals(make_df(closes, highs), "510300")
    assert any(s["key"].startswith("breakout") for s in sigs)
    # 高位后连续大跌 -> 回撤提醒
    closes = [120, 119, 118, 117, 116, 110, 100, 99, 98, 97]
    sigs = check_signals(make_df(closes), "510300")
    assert any(s["key"].startswith("dd_") for s in sigs)


def test_dedup_and_cooldown(monkeypatch):
    _flat_config(monkeypatch)
    today = date.today().isoformat()
    state = {"510300": {"sent": {f"breakout_{today}": today}}}
    sigs = [{"key": f"breakout_{today}", "rule": "新高", "direction": "x", "note": ""}]
    # 同日同键 -> 已发
    assert pick_new("510300", sigs, state) == []
    # 次日新键但冷却期内 -> 仍不发
    tomorrow = (date.today().fromordinal(date.today().toordinal() + 1)).isoformat()
    sigs2 = [{"key": f"breakout_{tomorrow}", "rule": "新高", "direction": "x", "note": ""}]
    state2 = {"510300": {"sent": {f"breakout_{date.today().isoformat()}": date.today().isoformat()}}}
    assert pick_new("510300", sigs2, state2) == []  # 冷却中
    # 金叉（状态型）不受冷却限制
    gold = [{"key": f"ma_gold_{tomorrow}", "rule": "金叉", "direction": "x", "note": ""}]
    assert len(pick_new("510300", gold, state2)) == 1


def test_commit_records_and_caps(monkeypatch):
    state: dict = {}
    fresh = [{"key": f"ma_gold_{i}", "rule": "r", "direction": "d", "note": "n"} for i in range(60)]
    commit("510300", fresh, state)
    sent = state["510300"]["sent"]
    assert len(sent) == 50  # 只保留最近 50 条


def test_signal_frame_drops_partial_bar_intraday():
    df = make_df([100, 101, 102], end=date.today().isoformat())
    intraday = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    after_close = datetime.now().replace(hour=15, minute=30, second=0, microsecond=0)
    assert len(signal_frame(df, intraday)) == len(df) - 1  # 盘中剔除今日未收盘bar
    assert len(signal_frame(df, after_close)) == len(df)   # 收盘后纳入


def test_parse_watchlist_override():
    assert parse_watchlist("etf:510300, stock:600519") == ["510300", "600519"]
    assert parse_watchlist("510500") == ["510500"]


def test_trading_hours():
    wed = datetime(2024, 6, 5, 10, 0)   # 周三盘中
    sat = datetime(2024, 6, 8, 10, 0)   # 周六
    wed_night = datetime(2024, 6, 5, 20, 0)
    assert in_trading_hours(wed) is True
    assert in_trading_hours(sat) is False
    assert in_trading_hours(wed_night) is False
