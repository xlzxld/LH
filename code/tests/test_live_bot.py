# -*- coding: utf-8 -*-
"""live_bot 核心逻辑的单元测试：resolve_mode 全矩阵 + FakeExchange 下单行为。

这两个测试是 F10 级别 bug（横幅说测试网、实际不下单/真下单）的"免疫疫苗"：
任何让模式解析与下单行为再次背离的改动，都会在这里红。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ch07_binance.live_bot as lb  # noqa: E402
from ch07_binance.live_bot import fmt_timeframe_seconds, resolve_mode, run_once  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    """所有测试的状态写入重定向到临时目录——绝不污染真实的 data/state/
    （历史事故：分数仓位测试曾把 bot_base=0.3 写进真实状态文件，
    之后每次 dry-run 都"以为"自己有持仓）。"""
    monkeypatch.setattr(lb, "STATE_FILE", tmp_path / "live_bot_state.json")


# ---------------------------------------------------------------- resolve_mode 全矩阵

@pytest.mark.parametrize("live,real,sandbox,has_keys,order_enabled,mode_contains", [
    (False, False, False, False, False, "DRY-RUN"),
    (False, True, True, True, False, "DRY-RUN"),          # 不加 --live 永远不下单
    (True, False, True, True, True, "TESTNET"),           # 测试网：--live 即真实下单（假钱）
    (True, True, True, True, True, "TESTNET"),            # 测试网上 --real 不改变沙箱事实
    (True, False, False, True, False, "未确认"),           # 真账户缺 --real：拒绝下单
    (True, True, False, True, True, "REAL"),              # 真钱三重确认齐全
    (True, True, False, False, False, "缺密钥"),           # 无 Key 永远不下单
    (True, False, False, False, False, "缺密钥"),
])
def test_resolve_mode_matrix(live, real, sandbox, has_keys, order_enabled, mode_contains):
    enabled, mode = resolve_mode(live, real, sandbox, has_keys)
    assert enabled is order_enabled
    assert mode_contains in mode


def test_resolve_mode_okx_trap():
    """Eng M4 的回归疫苗：EXCHANGE_ID=okx 时 BINANCE_TESTNET=true 是没人读的配置，
    实例并不在沙箱 —— 解析器必须以实例沙箱态为准，绝不能因配置旗标给出 TESTNET。"""
    enabled, mode = resolve_mode(live=True, real=False, sandbox_active=False, has_keys=True)
    assert enabled is False
    assert "TESTNET" not in mode


# ---------------------------------------------------------------- FakeExchange

class FakeExchange:
    """鸭子类型的假交易所：记录所有订单调用，余额可控。"""

    def __init__(self, base_free: float = 0.0):
        self.orders: list[tuple[str, float]] = []
        self._base_free = base_free
        self.ticker_price = 100.0

    def fetch_ticker(self, symbol):
        return {"last": self.ticker_price}

    def fetch_balance(self):
        return {"BTC": {"free": self._base_free, "used": 0.0}}

    def amount_to_precision(self, symbol, amount):
        return float(f"{amount:.6f}")

    def market(self, symbol):
        return {"limits": {"cost": {"min": 5.0}}}

    def create_market_buy_order(self, symbol, amount):
        self.orders.append(("BUY", amount))
        self._base_free += amount  # 成交：余额增加
        return {"id": "buy-1"}

    def create_market_sell_order(self, symbol, amount):
        self.orders.append(("SELL", amount))
        self._base_free = max(self._base_free - amount, 0.0)
        return {"id": "sell-1"}


def make_closes(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="h")
    p = pd.Series(closes, index=idx)
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p, "volume": 1.0})


GOLDEN = [100.0] * 8 + [50.0] * 5 + list(range(50, 90))    # 尾部上行 -> 金叉
DEATH = [100.0] * 8 + [90.0] * 5 + list(range(90, 50, -1))  # 尾部下行 -> 死叉


def with_candles(closes: list[float]):
    """把假K线注入 live_bot 的取数入口（patch 必须打在引用方命名空间）。"""
    orig = lb.fetch_crypto_ohlcv
    lb.fetch_crypto_ohlcv = lambda *a, **k: make_closes(closes)
    return orig


def _quiet_logger():
    logger = logging.getLogger("test_live_bot")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


# ---------------------------------------------------------------- run_once 行为

def test_run_once_never_orders_without_permission():
    """order_enabled=False：无论信号多强烈，一张单都不能发（F10 的行为契约）。"""
    orig = with_candles(GOLDEN)
    try:
        ex = FakeExchange()
        state = {"bot_base": 0.0}
        run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, order_enabled=False, state=state,
                 warned={}, logger=_quiet_logger())
        assert ex.orders == []
        assert state["bot_base"] == 0.0
    finally:
        lb.fetch_crypto_ohlcv = orig


def test_run_once_nan_signal_skips_round():
    """Eng M2 的回归疫苗：信号 NaN（数据不足）=> 本轮不动，绝不反向清仓。"""
    orig = with_candles([100.0, 101.0, 102.0])  # 远少于慢线窗口 -> 信号必为 NaN
    try:
        ex = FakeExchange(base_free=1.0)
        state = {"bot_base": 1.0}  # 机器人有持仓
        run_once(ex, "BTC/USDT", "1h", 3, 60, 100.0, order_enabled=True, state=state,
                 warned={}, logger=_quiet_logger())
        assert ex.orders == []  # 没有卖出！
        assert state["bot_base"] == 1.0
    finally:
        lb.fetch_crypto_ohlcv = orig


def test_run_once_golden_cross_buys_and_records_balance_delta():
    orig = with_candles(GOLDEN)
    try:
        ex = FakeExchange(base_free=0.0)
        state = {"bot_base": 0.0}
        run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, order_enabled=True, state=state,
                 warned={}, logger=_quiet_logger())
        assert len(ex.orders) == 1 and ex.orders[0][0] == "BUY"
        assert state["bot_base"] == pytest.approx(ex.orders[0][1])  # 余额差值记账
    finally:
        lb.fetch_crypto_ohlcv = orig


def test_run_once_death_cross_sells_only_bot_share():
    """F9 的行为契约：机器人只卖自己账本里的，用户手动买的币一根毛都不动。"""
    orig = with_candles(DEATH)
    try:
        ex = FakeExchange(base_free=5.0)  # 账户里 5 个币：4 个是用户手动买的
        state = {"bot_base": 1.0}         # 机器人只买过 1 个
        run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, order_enabled=True, state=state,
                 warned={}, logger=_quiet_logger())
        assert ex.orders == [("SELL", pytest.approx(1.0))]  # 只卖 1 个，不是 5 个
        assert state["bot_base"] == 0.0
    finally:
        lb.fetch_crypto_ohlcv = orig


def test_dust_position_is_abandoned_not_churned():
    """Eng M3 的回归疫苗：有仓但可卖余额低于最小下单额 -> 弃置清账，绝不死循环重试。"""
    orig = with_candles(DEATH)
    try:
        ex = FakeExchange(base_free=0.0001)  # 账本 0.06 个(6 USDT)算有仓，但可用余额是灰尘
        state = {"bot_base": 0.06}
        run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, order_enabled=True, state=state,
                 warned={}, logger=_quiet_logger())
        assert ex.orders == []            # 没有徒劳的卖单
        assert state["bot_base"] == 0.0   # 账本干净关账
    finally:
        lb.fetch_crypto_ohlcv = orig


def test_timeframe_validation_friendly():
    with pytest.raises(ValueError, match="非法K线周期"):
        fmt_timeframe_seconds("2M")
    assert fmt_timeframe_seconds("1h") == 3600


# ---------------------------------------------------------------- 止损（第 8 章风控在实盘侧落地）

def test_stop_loss_sells_when_price_breaks():
    """持仓均价 100、止损 5%、现价 90 -> 必须触发止损卖出，并锁仓(armed=False)。"""
    orig = with_candles(GOLDEN)  # 金叉信号，但止损优先级更高
    try:
        ex = FakeExchange(base_free=1.0)
        ex.ticker_price = 90.0
        state = {"bot_base": 1.0, "entry_price": 100.0}
        run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, order_enabled=True, state=state,
                 warned={}, logger=_quiet_logger(), stop_loss_pct=0.05)
        assert ex.orders == [("SELL", pytest.approx(1.0))]
        assert state["bot_base"] == 0.0
        assert state["entry_price"] is None
        assert state["armed"] is False
    finally:
        lb.fetch_crypto_ohlcv = orig


def test_stop_loss_not_triggered_above_line():
    """价格未击穿止损线时，止损不误触发（金叉且已持仓 -> 状态一致，无订单）。"""
    orig = with_candles(GOLDEN)
    try:
        ex = FakeExchange(base_free=1.0)
        ex.ticker_price = 98.0  # 高于 95 止损线
        state = {"bot_base": 1.0, "entry_price": 100.0}
        run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, order_enabled=True, state=state,
                 warned={}, logger=_quiet_logger(), stop_loss_pct=0.05)
        assert ex.orders == []
    finally:
        lb.fetch_crypto_ohlcv = orig


def test_stop_loss_blocks_reentry_until_new_cross():
    """止损后 armed=False：即使金叉信号也不重新买入（等新的 0->1 跳变才解锁）。"""
    orig = with_candles(GOLDEN)
    try:
        ex = FakeExchange(base_free=0.0)
        ex.ticker_price = 100.0
        # 止损后遗留的账本：空仓、锁仓、上一轮信号是金叉(1.0)
        state = {"bot_base": 0.0, "entry_price": None, "armed": False, "prev_target": 1.0}
        run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, order_enabled=True, state=state,
                 warned={}, logger=_quiet_logger(), stop_loss_pct=0.05)
        assert ex.orders == []        # 仍锁仓，不买入
        assert state["bot_base"] == 0.0
    finally:
        lb.fetch_crypto_ohlcv = orig


def test_buy_records_entry_price():
    """买入后必须记录持仓均价（供止损判断），均价 = 总花费 / 到手数量。"""
    orig = with_candles(GOLDEN)
    try:
        ex = FakeExchange(base_free=0.0)
        ex.ticker_price = 100.0
        state = {"bot_base": 0.0}
        run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, order_enabled=True, state=state,
                 warned={}, logger=_quiet_logger())
        assert state["bot_base"] > 0
        assert state["entry_price"] == pytest.approx(100.0)  # 花费 100 / 到手 1.0
    finally:
        lb.fetch_crypto_ohlcv = orig


# ---------------------------------------------------------------- 第三轮优化回归疫苗

def test_stop_loss_fires_even_when_signal_data_insufficient():
    """P0 疫苗：信号数据不足(NaN)绝不能挡住止损——有持仓时止损每轮都要检查。"""
    orig = with_candles([100.0, 101.0, 102.0])  # 少于慢线窗口 -> 目标必为 NaN
    try:
        ex = FakeExchange(base_free=1.0)
        ex.ticker_price = 90.0  # 击穿 100*0.95
        state = {"bot_base": 1.0, "entry_price": 100.0}
        run_once(ex, "BTC/USDT", "1h", 3, 60, 100.0, order_enabled=True, state=state,
                 warned={}, logger=_quiet_logger(), stop_loss_pct=0.05)
        assert ex.orders == [("SELL", pytest.approx(1.0))]  # 止损照常触发
        assert state["bot_base"] == 0.0
        assert state["armed"] is False
    finally:
        lb.fetch_crypto_ohlcv = orig


def test_stop_loss_wired_through_main_cli():
    """P0 疫苗：--stop-loss 必须在 main 的 argparse 里定义并传进 run_once。
    （历史事故：run_once 实现了止损、测试直接调 run_once 全绿，
    但 main 从未接线——真钱机器人默默无止损裸奔。）"""
    import inspect

    src = inspect.getsource(lb.main)
    assert 'add_argument("--stop-loss"' in src, "main 缺少 --stop-loss 参数定义"
    assert "stop_loss_pct=args.stop_loss" in src, "main 未把 --stop-loss 传给 run_once"


def test_fractional_target_buys_scaled_amount():
    """P0 疫苗：分数目标 0.3 是持有态——买入金额按 每笔预算×30% 缩放。"""
    orig_candles = with_candles(GOLDEN)
    orig_weights = lb.dual_ma_weights
    lb.dual_ma_weights = lambda df, f, s: orig_weights(df, f, s) * 0.3  # 目标 0.3
    try:
        ex = FakeExchange(base_free=0.0)
        ex.ticker_price = 100.0
        state = {"bot_base": 0.0}
        run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, order_enabled=True, state=state,
                 warned={}, logger=_quiet_logger())
        # 30 USDT @ 100 = 0.3 个（旧代码 target==1.0 判定会把它误判成空仓反而卖出）
        assert ex.orders == [("BUY", pytest.approx(0.3))]
        assert state["bot_base"] == pytest.approx(0.3)
        assert state["entry_price"] == pytest.approx(100.0)
    finally:
        lb.fetch_crypto_ohlcv = orig_candles
        lb.dual_ma_weights = orig_weights


def test_fractional_target_does_not_sell_existing_holding():
    """P0 疫苗：已持仓 + 分数目标(0.3) -> 状态一致，绝不能反向卖出。"""
    orig_candles = with_candles(GOLDEN)
    orig_weights = lb.dual_ma_weights
    lb.dual_ma_weights = lambda df, f, s: orig_weights(df, f, s) * 0.3
    try:
        ex = FakeExchange(base_free=1.0)
        ex.ticker_price = 100.0
        state = {"bot_base": 1.0, "entry_price": 100.0}
        run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, order_enabled=True, state=state,
                 warned={}, logger=_quiet_logger())
        assert ex.orders == []  # 旧代码会在这里把 1.0 全仓卖出（灾难）
    finally:
        lb.fetch_crypto_ohlcv = orig_candles
        lb.dual_ma_weights = orig_weights
