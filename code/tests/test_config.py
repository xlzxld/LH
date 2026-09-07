# -*- coding: utf-8 -*-
"""common/config 配置读取的回归测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common.config as cfg  # noqa: E402


def test_get_int_warns_on_decimal(monkeypatch, capsys):
    """C-02 回归：.env 里把整数写成了小数（如 MA_SLOW=60.5）要有警告，不能静默截断。"""
    monkeypatch.setenv("QA_TEST_INT", "60.5")
    val = cfg.get_int("QA_TEST_INT", 0)
    assert val == 60  # 行为不变：仍按截断值工作
    out = capsys.readouterr().out
    assert "QA_TEST_INT" in out and "60.5" in out  # 但必须吭声


def test_get_int_normal_value_no_warning(monkeypatch, capsys):
    monkeypatch.setenv("QA_TEST_INT", "60")
    assert cfg.get_int("QA_TEST_INT", 0) == 60
    assert capsys.readouterr().out == ""


def test_get_int_invalid_falls_back(monkeypatch, capsys):
    monkeypatch.setenv("QA_TEST_INT", "abc")
    assert cfg.get_int("QA_TEST_INT", 7) == 7
