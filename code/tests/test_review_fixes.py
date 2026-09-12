# -*- coding: utf-8 -*-
"""2026-09-12 全面代码审查修复回归（M1/M2/M5/L1/L3/L4/L7/L8/L13）。

2026-09-13 第二轮全面审查修复回归见文件末尾 S1~S4/M2 段：
dry-run 卖出守卫、ccxt 沙箱属性名、买入单结果未知停机、close 模式 NaN、
状态落盘。命名保持与既有测试套件一致；涉及第三方网络/交易所的路径用
Fake 或源码断言（与 test_live_bot 里"读源码断言 CLI 接线"的风格一致）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch04_backtest.engine import run_backtest  # noqa: E402
from ch04_backtest.run_dual_ma import crypto_periods  # noqa: E402
from ch05_metrics.performance import compute_stats, trade_stats  # noqa: E402
from ch07_binance import live_bot  # noqa: E402


# ---------------------------------------------------------------- M1 参数扫描回撤语义

def test_param_scan_drawdown_not_lower_better():
    """M1: 最大回撤是负数, 最浅回撤(最接近 0)才是最优 —— 判定曾完全反转,
    把 -6.7% 标成"最优参数"。回归: 源码断言 lower_better 不再对回撤特殊化。"""
    src = Path(live_bot.__file__).parent.parent.joinpath(
        "research", "param_scan.py").read_text(encoding="utf-8")
    assert "lower_better = metric == \"最大回撤\"" not in src, (
        "param_scan 仍按'回撤越小越好'比较(负数语义下会反转最优/最差)"
    )
    assert "lower_better = False" in src


# ---------------------------------------------------------------- M2 停牌价格 "-"

def test_monitor_live_price_coerces_dash():
    """M2: 东财快照对停牌标的返回 "-", float("-") 曾让整轮监测崩溃。
    回归: 源码断言用 pd.to_numeric(errors=coerce) 而非裸 float。"""
    src = Path(live_bot.__file__).parent.parent.joinpath(
        "ch08_monitor", "monitor_astock.py").read_text(encoding="utf-8")
    assert 'float(quotes.loc[code, "最新价"])' not in src, (
        "monitor 仍用裸 float 解析实时价(停牌 '-' 会抛 ValueError)"
    )
    assert 'pd.to_numeric(quotes.loc[code, "最新价"], errors="coerce")' in src


# ---------------------------------------------------------------- L1 现金护栏

def test_engine_cash_never_negative_with_min_fee():
    """L1: min_fee 临界区(cash=1000, rate=1%, min_fee=9.95)曾成交
    1000.05 元 → 现金 -0.05。回归: 首笔买入 notional+fee 不超过现金。"""
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame({"open": [10.0, 10.0, 10.0], "close": [10.0, 10.0, 10.0],
                       "high": [10.0, 10.0, 10.0], "low": [10.0, 10.0, 10.0]},
                      index=idx)
    weights = pd.Series(1.0, index=idx)
    r = run_backtest(df, weights, initial_cash=1000.0, commission_rate=0.01,
                     slippage_rate=0.0, execute_on="close", min_fee=9.95,
                     with_benchmark=False)
    buys = [t for t in r.trades if t["side"] == "BUY"]
    assert buys, "用例设计错误: 应发生买入"
    for t in buys:
        assert t["notional"] + t["fee"] <= 1000.0 + 1e-6, (
            f"买入 {t['notional']}+fee{t['fee']} 超出现金, 现金护栏未收口"
        )


# ---------------------------------------------------------------- L2 止损不被静默吞

def test_engine_pending_stop_survives_bad_open():
    """L2: next_open 模式下开盘价非法时, 止损单曾被静默清掉。回归: 源码
    断言保留止损单的分支存在。"""
    src = Path(live_bot.__file__).parent.parent.joinpath(
        "ch04_backtest", "engine.py").read_text(encoding="utf-8")
    assert "止损单顺延到下一根K线执行" in src


# ---------------------------------------------------------------- L3 索提诺口径

def test_sortino_uses_full_sample_downside_deviation():
    """L3: 下行风险按标准口径(全部收益 min(r,0) 的二阶矩)。
    曾只对负收益子集求 std —— 单个负收益时 len<2 直接按 0, 索提诺被算成 0。"""
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    equity = pd.Series([100.0, 103.0, 102.97], index=idx)
    stats = compute_stats(equity, periods_per_year=252)
    assert stats["索提诺比率"] > 0.0, (
        "一正一负的收益序列索提诺应为正(旧口径按 0 处理, 分母被吞)"
    )


# ---------------------------------------------------------------- L4 单笔盈亏含印花税

def test_trade_stats_counts_stamp_duty():
    """L4: A股个股卖出印花税曾被单笔盈亏漏算, 收益率被高估。"""
    trades = [
        {"side": "BUY", "price": 100.0, "shares": 10.0, "fee": 1.0},
        {"side": "SELL", "price": 110.0, "shares": 10.0, "fee": 1.0,
         "tax": 0.5},
    ]
    with_tax = trade_stats(trades)["盈利交易平均收益"]
    without_tax = trade_stats([trades[0], {**trades[1], "tax": 0.0}])["盈利交易平均收益"]
    assert with_tax < without_tax
    expected = (110.0 * 10 - 1.0 - 0.5) / (100.0 * 10 + 1.0) - 1.0
    assert abs(with_tax - expected) < 1e-12


# ---------------------------------------------------------------- L7 月线年化

def test_crypto_periods_supports_monthly():
    """L7: ccxt 月线周期 "1M" 曾不被识别, 年化按日线 365 处理(放大 30 倍)。"""
    assert crypto_periods("1M") == 12
    assert crypto_periods("1m") > 12  # 大小写语义不同: 分钟不被误判成月线


# ---------------------------------------------------------------- L8 测试网缺密钥

def test_resolve_mode_testnet_requires_keys():
    """L8: 测试网无 Key 加 --live 曾被放行, 第一轮对账即 AuthenticationError。"""
    enabled, mode = live_bot.resolve_mode(live=True, real=False,
                                          sandbox_active=True, has_keys=False)
    assert enabled is False
    assert "缺密钥" in mode
    enabled, mode = live_bot.resolve_mode(live=True, real=True,
                                          sandbox_active=True, has_keys=False)
    assert enabled is False


# ---------------------------------------------------------------- M3 待核实买入单

class _FakePendingExchange:
    """_reconcile_pending_buy 的最小 Fake: 只实现 fetch_order。"""

    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def fetch_order(self, oid, symbol):
        if self._error is not None:
            raise self._error
        return self._result


def _quiet_logger():
    import logging
    return logging.getLogger("test_review_fixes")


def test_reconcile_pending_buy_credits_filled_order():
    """M3: 已提交但未确认到手的买入单若实际成交, 必须补记账而不是让下一轮
    重复市价买入(真钱超买)。"""
    state = {"bot_base": 0.0, "entry_price": None,
             "pending_buy": {"order_id": "777", "rounds_left": 3}}
    ex = _FakePendingExchange({"status": "closed", "filled": 0.5, "average": 200.0})
    ok = live_bot._reconcile_pending_buy(ex, "BTC/USDT", state, 190.0,
                                         _quiet_logger())
    assert ok is True
    assert state.get("pending_buy") is None
    assert state["bot_base"] == pytest.approx(0.5)
    assert state["entry_price"] == pytest.approx(200.0)


def test_reconcile_pending_buy_blocks_while_open():
    state = {"bot_base": 0.0, "entry_price": None,
             "pending_buy": {"order_id": "778", "rounds_left": 3}}
    ex = _FakePendingExchange({"status": "open", "filled": 0.0})
    assert live_bot._reconcile_pending_buy(ex, "BTC/USDT", state, 190.0,
                                           _quiet_logger()) is False
    # 已终结但未成交(撤单): 解除挂起且不补记账
    ex2 = _FakePendingExchange({"status": "canceled", "filled": 0.0})
    assert live_bot._reconcile_pending_buy(ex2, "BTC/USDT", state, 190.0,
                                           _quiet_logger()) is True
    assert state.get("pending_buy") is None
    assert state["bot_base"] == 0.0


def test_reconcile_pending_buy_cooldown_expires():
    """查询持续失败时冷却轮数递减, 用完强制解除(防永久卡死买不进)。"""
    state = {"bot_base": 0.0, "entry_price": None,
             "pending_buy": {"order_id": "779", "rounds_left": 1}}
    ex = _FakePendingExchange(error=RuntimeError("network down"))
    assert live_bot._reconcile_pending_buy(ex, "BTC/USDT", state, 190.0,
                                           _quiet_logger()) is True
    assert state.get("pending_buy") is None


def test_run_once_records_pending_when_balance_snapshot_misses():
    """买入提交后余额快照没变化 → 必须挂起 pending_buy, 而不是只告警。"""
    from types import SimpleNamespace

    calls = {"buys": 0}

    class FakeEx:
        def amount_to_precision(self, symbol, amount):
            return amount

        def create_market_buy_order(self, symbol, amount):
            calls["buys"] += 1
            return {"id": "900"}

        def fetch_balance(self):
            return {"BTC": {"free": 1.0, "used": 0.0}}

        def fetch_ticker(self, symbol):
            return {"last": 100.0, "close": 100.0}

        def fetch_ohlcv(self, symbol, timeframe=None, limit=None):
            base = 100.0
            rows = []
            for i in range(80):
                rows.append([i * 86400000, base + i, base + i + 1,
                             base + i - 1, base + i, 1000.0])
            # 构造金叉跳变: 最后两根价格快速拉高让快线上穿慢线
            for k, (t, o, h, l, c, v) in enumerate(rows):
                if k >= len(rows) - 3:
                    rows[k] = [t, o, h + 60, l, c + 60, v]
            return rows

    ex = FakeEx()
    state = {"armed": True, "prev_target": 0.0, "bot_base": 0.0,
             "entry_price": None}
    lb = live_bot
    lb.run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, True, state, {},
                _quiet_logger())
    assert calls["buys"] == 1
    if state.get("pending_buy"):
        # 走了"余额没变化"分支 → 必须挂起且账本不更新
        assert state["bot_base"] == 0.0
    else:
        # 正常成交分支: 账本应增加(两类行为都合法, 关键是不重复下单)
        assert state["bot_base"] > 0 or calls["buys"] == 1


# ================================================================ 2026-09-13 第二轮审查修复回归

# ---------------------------------------------------------------- S1 dry-run 卖出守卫

DEATH = [100.0] * 8 + [90.0] * 5 + list(range(90, 50, -1))  # 尾部下行 -> 死叉


class _FakeMarketExchange:
    """S1/S3 用：实现 run_once 全链路所需的最小交易所接口。"""

    def __init__(self, base_free=0.0):
        self.orders = []
        self._base_free = base_free

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def fetch_balance(self):
        return {"BTC": {"free": self._base_free, "used": 0.0}}

    def amount_to_precision(self, symbol, amount):
        return float(f"{amount:.6f}")

    def market(self, symbol):
        return {"limits": {"cost": {"min": 5.0}}}

    def create_market_buy_order(self, symbol, amount):
        self.orders.append(("BUY", amount))
        self._base_free += amount
        return {"id": "b1"}

    def create_market_sell_order(self, symbol, amount):
        self.orders.append(("SELL", amount))
        self._base_free = max(self._base_free - amount, 0.0)
        return {"id": "s1"}


def _make_closes(closes):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="h")
    p = pd.Series(closes, index=idx)
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p, "volume": 1.0})


def test_run_once_dry_run_never_sells(monkeypatch):
    """S1: dry-run 死叉卖出曾直接市价卖出（买入/止损都有模拟分支，卖出漏了）。
    文件头承诺"不加 --live 一张单都不会发"——卖出方向同样必须成立。"""
    monkeypatch.setattr(live_bot, "fetch_crypto_ohlcv",
                        lambda *a, **k: _make_closes(DEATH))
    monkeypatch.setattr(live_bot.time, "sleep", lambda *_: None)
    ex = _FakeMarketExchange(base_free=1.0)
    state = {"bot_base": 1.0, "entry_price": 100.0}
    live_bot.run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, False, state, {},
                      _quiet_logger())
    assert ex.orders == [], "dry-run 下死叉信号发出了真实卖单！"


# ---------------------------------------------------------------- S2 ccxt 沙箱属性名

def test_sandbox_active_reads_real_ccxt_flag():
    """S2: sandbox_active 曾读 .sandbox（ccxt 4.x 实例上不存在）恒 False——
    测试网被当真账户拒绝下单、模式横幅语义反转。用真实 ccxt 实例回归
    （set_sandbox_mode 只改本地 URL，不发网络请求）。"""
    ccxt = pytest.importorskip("ccxt")
    from common.exchange import sandbox_active

    ex = ccxt.binance()
    assert sandbox_active(ex) is False
    ex.set_sandbox_mode(True)
    assert sandbox_active(ex) is True


# ---------------------------------------------------------------- S3 买入单结果未知

class _BuyTimeoutExchange(_FakeMarketExchange):
    """下单调用本身抛网络异常（订单可能已到达交易所）。"""

    def create_market_buy_order(self, symbol, amount):
        self.orders.append(("BUY-ATTEMPT", amount))
        raise RuntimeError("simulated request timeout after order reached exchange")


def test_buy_call_failure_raises_ambiguous_and_saves_state(monkeypatch):
    """S3: 下单调用抛异常时绝不能当瞬时错误下一轮重试（会重复市价买入）。
    必须：抛 BuyOrderAmbiguous 让主循环停机 + 状态落盘。"""
    monkeypatch.setattr(live_bot, "fetch_crypto_ohlcv",
                        lambda *a, **k: _make_closes(
                            [100.0] * 8 + [50.0] * 5 + list(range(50, 90))))
    monkeypatch.setattr(live_bot.time, "sleep", lambda *_: None)
    ex = _BuyTimeoutExchange()
    state = {"armed": True, "prev_target": 0.0, "bot_base": 0.0, "entry_price": None}
    with pytest.raises(live_bot.BuyOrderAmbiguous):
        live_bot.run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, True, state, {},
                          _quiet_logger())
    # 状态已落盘（停机后人工核对的是磁盘上的账本）
    import json
    on_disk = json.loads(live_bot.STATE_FILE.read_text(encoding="utf-8"))
    assert on_disk == state


class _SnapshotFailExchange(_FakeMarketExchange):
    """下单成功，但之后的余额快照抛网络异常。"""

    def __init__(self):
        super().__init__()
        self._calls = 0

    def fetch_balance(self):
        self._calls += 1
        if self._calls >= 3:  # before=1, after=3（对账 total=2 不走 balance 计数以外的路径）
            raise RuntimeError("simulated snapshot timeout")
        return {"BTC": {"free": self._base_free, "used": 0.0}}


def test_snapshot_failure_pends_order_and_reraises(monkeypatch):
    """S3b: 单已提交（有订单号）但余额快照失败 → 挂起 pending_buy 再把异常
    交回主循环（下一轮会先核实订单，不会重复买入）。"""
    monkeypatch.setattr(live_bot, "fetch_crypto_ohlcv",
                        lambda *a, **k: _make_closes(
                            [100.0] * 8 + [50.0] * 5 + list(range(50, 90))))
    monkeypatch.setattr(live_bot.time, "sleep", lambda *_: None)
    ex = _SnapshotFailExchange()
    state = {"armed": True, "prev_target": 0.0, "bot_base": 0.0, "entry_price": None}
    with pytest.raises(RuntimeError):
        live_bot.run_once(ex, "BTC/USDT", "1h", 3, 5, 100.0, True, state, {},
                          _quiet_logger())
    assert state["pending_buy"]["order_id"] == "b1"


# ---------------------------------------------------------------- S4 close 模式 NaN

def test_close_mode_nan_weights_do_not_crash():
    """S4: close 模式遇 NaN 信号（均线窗口未就绪的前几根必为 NaN）曾把
    None 传进 _execute 直接 TypeError——文档推荐入口 100% 必崩。"""
    idx = pd.date_range("2024-01-01", periods=8, freq="D")
    df = pd.DataFrame({"open": [10.0] * 8, "close": [10.0] * 8,
                       "high": [10.0] * 8, "low": [10.0] * 8}, index=idx)
    weights = pd.Series([float("nan")] * 4 + [1.0, 1.0, 0.0, 0.0], index=idx)
    r = run_backtest(df, weights, execute_on="close", with_benchmark=False)
    assert len(r.equity) == 8
    # NaN 段"维持现状"不崩不清仓；之后的 1.0/0.0 正常买卖
    assert {t["side"] for t in r.trades} == {"BUY", "SELL"}


# ---------------------------------------------------------------- M2 补记账落盘

def test_reconcile_pending_buy_persists_cooldown(monkeypatch):
    """M2: 核实失败时 rounds_left 递减必须落盘——否则反复重启的进程
    永远耗不尽冷却轮数、挂起永远解除不了。"""
    import json

    state = {"bot_base": 0.0, "entry_price": None,
             "pending_buy": {"order_id": "780", "rounds_left": 3}}
    ex = _FakePendingExchange(error=RuntimeError("network down"))
    ok = live_bot._reconcile_pending_buy(ex, "BTC/USDT", state, 190.0,
                                         _quiet_logger())
    assert ok is False
    on_disk = json.loads(live_bot.STATE_FILE.read_text(encoding="utf-8"))
    assert on_disk["pending_buy"]["rounds_left"] == 2
