# -*- coding: utf-8 -*-
"""
交易所实例工厂：全项目唯一创建 ccxt 交易所对象的地方。

网络现实（2026 年，大陆网络实测）：
    api.binance.com          —— 通常被墙，实盘交易需要代理
    data-api.binance.vision  —— 币安官方公共行情域名，大陆可直连（拉K线/价格够用）
    testnet.binance.vision   —— 测试网，大陆可直连（注册 GitHub 账号就能拿假钱 Key）
所以本项目默认：公共行情走 data-api.binance.vision；模拟盘走 testnet；
真实下单（api.binance.com）需要你自备网络条件，第 9 章文档有详细说明。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import config  # noqa: E402

# 币安官方公共行情域名（无需 Key，全球可访问，大陆可直连）
DEFAULT_DATA_HOST = "https://data-api.binance.vision/api/v3"


def make_exchange(exchange_id: str | None = None, *, testnet: bool | None = None,
                  with_keys: bool = True):
    """
    创建一个配置好的 ccxt 交易所实例。

    :param exchange_id: 默认取 .env 的 EXCHANGE_ID（binance）
    :param testnet: True/False 强制指定；None 则取 .env 的 BINANCE_TESTNET。
        注意（Eng 评审 M4 的教训）：这个参数只对 binance 生效——判断实例真实
        沙箱态请用下面的 sandbox_active()，别信配置旗标
    :param with_keys: 是否附带 API Key（拉公共行情不需要）
    """
    import ccxt

    ex_id = (exchange_id or config.exchange_id()).lower()
    if not hasattr(ccxt, ex_id):
        raise ValueError(f"ccxt 不支持交易所 {ex_id!r}")

    options = {"defaultType": "spot", "fetchMarkets": ["spot"]}  # 只加载现货，更快更稳
    kwargs = {"enableRateLimit": True, "options": options}
    if with_keys:
        if ex_id == "binance":
            kwargs["apiKey"] = config.get("BINANCE_API_KEY", "")
            kwargs["secret"] = config.get("BINANCE_API_SECRET", "")
        elif ex_id == "okx":
            # OKX 需要三件套：Key + Secret + 口令（Passphrase）
            kwargs["apiKey"] = config.get("OKX_API_KEY", "")
            kwargs["secret"] = config.get("OKX_API_SECRET", "")
            kwargs["password"] = config.get("OKX_PASSPHRASE", "")

    exchange = getattr(ccxt, ex_id)(kwargs)

    if testnet is None:
        testnet = config.use_testnet()
    if testnet and ex_id == "binance":
        exchange.set_sandbox_mode(True)  # 公共+私有接口全部指向 testnet.binance.vision
    elif ex_id == "binance":
        # 真实行情换用大陆可达的公共数据域名；私有接口仍是 api.binance.com（需网络条件）
        exchange.urls["api"]["public"] = config.get("BINANCE_DATA_HOST", DEFAULT_DATA_HOST)
        # 防呆：ccxt 版本升级可能改掉这个键，静默失效会让大陆用户撞墙。启动即断言
        if "vision" not in str(exchange.urls["api"].get("public", "")):
            raise RuntimeError("BINANCE_DATA_HOST 覆盖未生效（ccxt 内部 URL 结构可能已变化），"
                               "请升级或降级 ccxt，或检查 common/exchange.py")
    return exchange


def api_key_name(ex_id: str | None = None) -> str:
    """该交易所 API Key 在 .env 里的键名（与 make_exchange 的配钥逻辑一一对应）。

    消灭"各自手写字典"的漂移：live_bot 判缺密钥、testnet_check 判跳过，
    都必须问这里——EXCHANGE_ID=okx 时却去读 BINANCE_API_KEY 就是这类漂移的产物。
    """
    ex_id = (ex_id or config.exchange_id()).lower()
    return {"binance": "BINANCE_API_KEY", "okx": "OKX_API_KEY"}.get(ex_id, "BINANCE_API_KEY")


def sandbox_active(exchange) -> bool:
    """读交易所实例的真实沙箱态（binance 用了 set_sandbox_mode 时为 True）。
    下单开关必须以这里的结果为准，不要读配置旗标（见 live_bot.resolve_mode）。"""
    return bool(getattr(exchange, "sandbox", False))
