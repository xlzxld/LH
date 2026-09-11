# -*- coding: utf-8 -*-
"""position_sizing 的单元测试：四种仓位法的守卫与边界（该模块此前零覆盖）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch06_risk.position_sizing import (  # noqa: E402
    atr_risk, fixed_amount, fixed_fraction, kelly, main,
)


def test_fixed_amount_capped_by_equity():
    assert fixed_amount(equity=10_000, per_trade=3_000) == 3_000
    assert fixed_amount(equity=1_000, per_trade=3_000) == 1_000   # 不超过总资金
    assert fixed_amount(equity=10_000, per_trade=10_000) == 10_000


def test_fixed_fraction_rejects_out_of_range():
    assert fixed_fraction(equity=100_000, fraction=0.2) == pytest.approx(20_000)
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            fixed_fraction(equity=100_000, fraction=bad)


def test_atr_risk_uses_two_atr_stop_distance():
    # 允许亏 1% = 1000 元；止损距离 = 2 × 1% = 2% → 仓位市值 1000 / 0.02 = 50000
    assert atr_risk(equity=100_000, risk_pct=0.01, atr_pct=0.01) == pytest.approx(50_000)
    with pytest.raises(ValueError):
        atr_risk(equity=100_000, risk_pct=0.01, atr_pct=0.0)


def test_kelly_halves_and_floors_at_zero():
    # W=0.5, R=2 → f = 0.5 - 0.5/2 = 0.25；半凯利 = 0.125
    assert kelly(win_rate=0.5, win_loss_ratio=2.0) == pytest.approx(0.125)
    assert kelly(win_rate=0.5, win_loss_ratio=2.0, halve=False) == pytest.approx(0.25)
    # 负期望 → 归零，绝不给出负仓位
    assert kelly(win_rate=0.3, win_loss_ratio=1.0) == 0.0
    with pytest.raises(ValueError):
        kelly(win_rate=0.0, win_loss_ratio=2.0)
    with pytest.raises(ValueError):
        kelly(win_rate=0.5, win_loss_ratio=0.0)


def test_equity_must_be_positive(monkeypatch, capsys):
    """回归 H-08：--equity 为 0/负数时曾抛裸 ZeroDivisionError。

    修复前：被 ZeroDivisionError 打断（本用例失败）；
    修复后：argparse 给出中文提示并 SystemExit(2)。
    三种方法都覆盖——kelly 分支正是当初触发除零的那条路径。
    """
    cases = [
        ["--method", "fixed_amount", "--equity", "0", "--per-trade", "1000"],
        ["--method", "fixed_fraction", "--equity", "-5000", "--fraction", "0.2"],
        ["--method", "kelly", "--equity", "0", "--win-rate", "0.5", "--win-loss-ratio", "2"],
    ]
    for argv in cases:
        monkeypatch.setattr(sys, "argv", ["position_sizing.py", *argv])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2                     # argparse 参数错误码
        assert "equity" in capsys.readouterr().err     # 中文提示里点名了参数
