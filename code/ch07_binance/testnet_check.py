# -*- coding: utf-8 -*-
"""
第 9 章配套脚本：币安（模拟盘/实盘）连通性自检。

运行前先在 .env 里配置：
    BINANCE_API_KEY=xxx
    BINANCE_API_SECRET=xxx
    BINANCE_TESTNET=true        # true=测试网（推荐），false=真实账户

用法：
    python code/ch07_binance/testnet_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import config  # noqa: E402
from common.exchange import api_key_name, sandbox_active  # noqa: E402


def make_exchange(testnet: bool):
    """创建 ccxt 币安实例（统一走公共工厂）。"""
    from common.exchange import make_exchange as _factory
    return _factory(testnet=testnet)


def main() -> None:
    testnet = config.use_testnet()
    exchange = make_exchange(testnet)
    # 横幅必须读实例的真实沙箱态（与 live_bot 的 resolve_mode 同一教训）：
    # EXCHANGE_ID=okx 等非币安交易所不受 BINANCE_TESTNET 开关控制，配置旗标说了不算
    sandbox = sandbox_active(exchange)
    tag = "沙箱/测试网" if sandbox else "真实账户（小心！）"
    print(f"目标: {exchange.id} {tag}\n")  # 交易所名与沙箱态都随实例走，别信配置

    # ---- 测试 1：公开行情（不需要 API Key，只测网络）
    try:
        ticker = exchange.fetch_ticker("BTC/USDT")
        print(f"[1/3] 公共行情 OK：BTC/USDT 最新价 = {ticker['last']}")
    except Exception as exc:
        print(f"[1/3] 公共行情失败（多半是网络问题，国内需代理）: {exc}")
        return

    # ---- 测试 2：账户读取权限
    if not config.get(api_key_name(config.exchange_id())):
        print("[2/3] 跳过（未配置 API Key）。去 testnet.binance.vision 注册即可拿到测试 Key")
        return
    try:
        balance = exchange.fetch_balance()
        usdt = balance.get("USDT", {}).get("free", 0)
        print(f"[2/3] 账户余额 OK：可用 USDT = {usdt}")
    except Exception as exc:
        print(f"[2/3] 读取账户失败（检查 Key 是否填对、IP 是否在白名单）: {exc}")
        return

    # ---- 测试 3：最小交易权限验证 —— 挂一张远离市价的测试限价单，
    #      无论挂上与否都在 finally 里按订单 id 撤掉（绝不留残留挂单在账户里）
    try:
        price = exchange.fetch_ticker("BTC/USDT")["last"]
        order_id = None
        try:
            order = exchange.create_limit_buy_order("BTC/USDT", 0.00001, round(price * 0.1, 2))
            order_id = order.get("id")
            print("[3/3] 下单权限 OK（测试限价单已提交，即将撤销）")
        except Exception as inner:
            code = getattr(inner, "code", None) or getattr(inner, "errno", None)
            text = str(inner)
            # 按错误码/错误类判断，而非文案匹配（ccxt 版本间文案会变）
            if code in (-2019, -1013, -4164) or type(inner).__name__ in (
                    "InvalidOrder", "InsufficientFunds", "MinimumNotional"):
                print(f"[3/3] 下单权限 OK（测试单因金额过小被拒 {type(inner).__name__}，这正是预期）")
            else:
                print(f"[3/3] 下单权限异常: {text}")
        finally:
            if order_id is not None:
                try:
                    exchange.cancel_order(order_id, "BTC/USDT")
                    print("      测试挂单已撤销，账户不留残留单")
                except Exception as cancel_exc:
                    print(f"      [警告] 撤单失败，请手动到网页撤销测试挂单! id={order_id}: {cancel_exc}")
    except Exception as exc:
        print(f"[3/3] 测试异常: {exc}")


if __name__ == "__main__":
    main()
