# -*- coding: utf-8 -*-
"""common/exchange.py 工厂辅助函数的单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.exchange import api_key_name  # noqa: E402


def test_api_key_name_per_exchange():
    """键名映射必须与 make_exchange 的配钥逻辑一一对应（消灭各处手写字典漂移）。"""
    assert api_key_name("binance") == "BINANCE_API_KEY"
    assert api_key_name("OKX") == "OKX_API_KEY"  # 大小写不敏感


def test_api_key_name_unknown_falls_back():
    """未收录的交易所沿用历史行为：回退币安键名（而不是 KeyError）。"""
    assert api_key_name("bybit") == "BINANCE_API_KEY"


def test_api_key_name_reads_env_when_omitted(monkeypatch):
    monkeypatch.setenv("EXCHANGE_ID", "okx")
    assert api_key_name() == "OKX_API_KEY"
