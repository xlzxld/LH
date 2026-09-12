# -*- coding: utf-8 -*-
"""测试共享夹具：所有测试的状态写入一律重定向到临时目录。

历史事故一：分数仓位测试曾把 bot_base=0.3 写进真实状态文件，之后每次
dry-run 都"以为"自己有持仓。
历史事故二：test_review_fixes 直接调 run_once 把 pending_buy(order_id=900)
写进了 data/state/live_bot_state.json —— 用户下次真跑机器人时会去核实一笔
不存在的订单。

任何新测试文件都自动获得本隔离，无需（也不应）各自再写 STATE_FILE 夹具。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import ch07_binance.live_bot as lb  # noqa: E402
import ch08_monitor.monitor_astock as mon  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_state_files(tmp_path, monkeypatch):
    """把 live_bot / monitor 的状态文件指向 tmp_path，绝不污染 data/state/。"""
    monkeypatch.setattr(lb, "STATE_FILE", tmp_path / "live_bot_state.json")
    monkeypatch.setattr(mon, "STATE_FILE", tmp_path / "monitor_state.json")
