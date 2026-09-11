# -*- coding: utf-8 -*-
"""
第 9 章配套脚本：币安现货双均线实盘机器人（7x24 轮询版）。

【安全体系 —— 每一道都必须能独立讲清楚】
  1. 模式解析 resolve_mode()：order_enabled 只由"是否连着沙箱/是否真钱确认"决定，
     与展示横幅彻底分离（历史教训：曾有版本横幅写 TESTNET、实际连着主网）。
  2. 默认 dry-run：不加 --live 一张单都不会发。
  3. 真钱三重确认：--live + --real + 命令行输入确认短语，缺一不可。
  4. 只动自己的仓位：机器人用状态文件记录"自己买入的数量"，卖出只卖自己买的，
     绝不清算你手动买的币（想混用请用独立的子账户）。
  5. API Key 权限最小化：只勾"读取 + 现货交易"，绝不勾提现，绑定 IP 白名单。

用法：
    python code/ch07_binance/live_bot.py                      # dry-run，绝对安全
    python code/ch07_binance/live_bot.py --live               # 测试网真实下单（推荐练习）
    python code/ch07_binance/live_bot.py --live --real        # 真钱（还需输入确认短语）
    python code/ch07_binance/live_bot.py --live --stop-loss 0.05   # 加 5% 止损（见第 8 章）
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

sys_path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(sys_path))

from ch03_data.datasource import fetch_crypto_ohlcv  # noqa: E402
from ch04_backtest.strategy import dual_ma_weights  # noqa: E402
from common import config  # noqa: E402
from common.exchange import api_key_name  # noqa: E402
from common.notify import send_text  # noqa: E402
from common.state import load_state, save_state  # noqa: E402

LOG_FILE = config.DATA_DIR / "live_bot.log"
STATE_FILE = config.STATE_DIR / "live_bot_state.json"

# 低于该市值（USDT）的持仓视为灰尘：多数主流交易对的最小下单额在 5~10 USDT
DUST_QUOTE = 5.0
VALID_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"}
REAL_MONEY_PHRASE = "I-ACCEPT-FULL-LEGAL-RESPONSIBILITY"


def setup_logging() -> logging.Logger:
    config.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
        ],
    )
    return logging.getLogger("live_bot")


# ---------------------------------------------------------------- 模式解析

def resolve_mode(live: bool, real: bool, sandbox_active: bool, has_keys: bool) -> tuple[bool, str]:
    """
    把"用户想要什么"解析成"实际会发生什么"。纯函数（无副作用），全矩阵有测试覆盖。

    返回 (order_enabled, 模式描述)。
    教训（Eng 评审 M4/F10）：下单开关只能由**交易所实例的真实状态**决定——
    沙箱态要从实例属性读，不能信 .env 的旗标（EXCHANGE_ID=okx 时
    BINANCE_TESTNET=true 是个没人读的配置，横幅却照印 TESTNET）。
    """
    if not live:
        return False, "DRY-RUN（不发送任何订单）"
    if sandbox_active:
        return True, "TESTNET（测试网假钱，真实下单）"
    if not has_keys:
        return False, "LIVE-缺密钥（无法交易）"
    if real:
        return True, "REAL（真金白银！）"
    return False, "LIVE-未确认（缺 --real，本轮不下单）"


def make_exchange():
    """创建交易所实例（统一走 common/exchange.py 工厂）。"""
    from common.exchange import make_exchange as _factory, sandbox_active

    exchange = _factory()
    return exchange, sandbox_active(exchange)


# ---------------------------------------------------------------- 余额与状态

def get_free_balance(exchange, symbol: str) -> float:
    """查询基础币的可用余额（锁定中的不算——那些挂单成交前卖不了）。"""
    base = symbol.split("/")[0]
    balance = exchange.fetch_balance()
    return float((balance.get(base) or {}).get("free") or 0.0)


def min_notional(exchange, symbol: str) -> float:
    """交易所最小下单额（USDT）。取不到市场元数据时用保守默认 5。"""
    try:
        market = exchange.market(symbol)
        cost = ((market.get("limits") or {}).get("cost") or {}).get("min")
        return float(cost) if cost else 5.0
    except Exception as exc:
        print(f"[警告] 读取 {getattr(exchange, 'id', '?')} 最小下单额失败（{exc}），按保守默认 5 USDT 处理")
        return 5.0


def total_base_balance(exchange, symbol: str) -> float:
    """全仓余额（自由+锁定），只用于"账户里有不属于机器人的币"的对账告警。"""
    base = symbol.split("/")[0]
    try:
        balance = exchange.fetch_balance()
        entry = balance.get(base) or {}
        return float(entry.get("free") or 0.0) + float(entry.get("used") or 0.0)
    except Exception as exc:
        print(f"[警告] 读取 {base} 全仓余额失败（{exc}），本轮对账按 0 处理")
        return 0.0


# ---------------------------------------------------------------- 单轮逻辑

def run_once(exchange, symbol: str, timeframe: str, fast: int, slow: int,
             quote_per_trade: float, order_enabled: bool, state: dict,
             warned: dict, logger, stop_loss_pct: float | None = None) -> None:
    """执行一轮"拉数据 -> 算信号 -> 止损检查 -> 调仓"。所有持久化决策都记在 state。

    stop_loss_pct：止损比例（如 0.05 = 从持仓均价亏 5% 触发市价卖出）。None=不启用。
    这是第 8 章风控在实盘侧的落地：回测引擎有止损（engine.stop_loss_pct），
    实盘机器人此前一直缺这一道，导致"回测带止损、实盘裸奔"的语义裂痕。
    """
    df = fetch_crypto_ohlcv(symbol, timeframe=timeframe, limit=slow + 10, exchange=exchange)
    if len(df) < 2:
        logger.info("K线数据不足，本轮跳过")
        return
    closed = df.iloc[:-1]  # 最后一根K线还没收盘：拿它算信号=偷看未来，剔掉
    weights = dual_ma_weights(closed, fast, slow)
    target = weights.iloc[-1]

    price = float(exchange.fetch_ticker(symbol)["last"])  # 执行定价用实时价，不用陈旧的收盘价
    base = symbol.split("/")[0]
    bot_holding = float(state.get("bot_base", 0.0))
    entry_price = state.get("entry_price")  # 持仓均价（止损基准），None=空仓
    prev_target = state.get("prev_target")  # 上一轮信号（判断跳变，用于止损后再入场门）
    in_position = bot_holding * price > DUST_QUOTE  # 决策只看机器人自己的账本
    # NaN 的契约含义是"数据不足，维持现状"，绝不是清仓；
    # 分数目标（如 0.3）是持有态——绝不能把持有态误判成空仓而反向卖出
    wanted = None if pd.isna(target) else bool(target > 0)

    if wanted is None:
        target_desc = "维持现状(数据不足)"
    elif target >= 1.0:
        target_desc = "满仓"
    elif target > 0:
        target_desc = f"{target:.0%}仓位"
    else:
        target_desc = "空仓"
    logger.info(f"{symbol} 价格={price:.2f} MA{fast}x{slow} 目标={target_desc} "
                f"机器人持仓={bot_holding:.6f} {base}（{'有仓' if in_position else '空仓'}）")

    # 对账：账户里出现了远超机器人账本的币 → 提醒（那些不会被卖出，但你自己要知道）
    total = total_base_balance(exchange, symbol)
    if order_enabled and total > bot_holding + DUST_QUOTE / price * 10 and not warned.get("mismatch"):
        logger.warning(f"账户实际 {base} 余额({total:.6f}) 高于机器人账本({bot_holding:.6f})。"
                       f"机器人只会交易自己账本内的份额；建议给机器人用独立子账户")
        warned["mismatch"] = True

    # ---- 止损检查（优先级最高，先于信号有效性——回测引擎也是每根bar都查，
    #      否则信号数据不足的轮次会让持仓"裸奔"）----
    stop_hit = (
        stop_loss_pct is not None and in_position and entry_price is not None
        and price <= float(entry_price) * (1.0 - stop_loss_pct)
    )
    if stop_hit:
        logger.warning(f"{symbol} 止损触发：价格 {price:.2f} 跌破均价 {float(entry_price):.2f} 的 "
                       f"{stop_loss_pct:.0%} 止损线")
        free_now = get_free_balance(exchange, symbol)
        sell_amount = min(bot_holding, free_now)
        if sell_amount * price < min_notional(exchange, symbol):
            logger.info("[止损] 可卖余额为灰尘，直接弃置清账")
            state["bot_base"] = 0.0
            state["entry_price"] = None
        elif not order_enabled:
            logger.info(f"[模拟] 止损将市价卖出 {sell_amount:.6f} {base}")
            state["bot_base"] = 0.0
            state["entry_price"] = None
        else:
            order = exchange.create_market_sell_order(
                symbol, exchange.amount_to_precision(symbol, sell_amount))
            time.sleep(2)  # 给成交与余额结算留一点时间
            after = get_free_balance(exchange, symbol)
            sold = max(free_now - after, 0.0)  # 余额差值记账：防部分成交导致账实漂移
            state["bot_base"] = round(max(bot_holding - sold, 0.0), 8)
            if state["bot_base"] <= 1e-12:
                state["entry_price"] = None
            logger.info(f"[成交] 止损卖出单 id={order.get('id')}，实际卖出 {sold:.6f} {base}")
            send_text("🛑 机器人止损",
                      f"{symbol} 价格 {price:.2f} 跌破止损线，卖出 {sold:.6f} {base}")
        state["armed"] = False        # 止损后锁仓，等新的 空仓→持有 跳变才重新入场
        if not pd.isna(target):
            state["prev_target"] = float(target)  # NaN 不写入状态（会污染 JSON 与跳变判断）
        save_state(STATE_FILE, state)
        return

    if wanted is None:
        logger.info(f"{symbol} 信号数据不足（慢线窗口未就绪），本轮不动（止损已检查）")
        return

    # ---- 金叉跳变解锁 armed（止损后再入场的门，与回测引擎语义一致）----
    if prev_target == 0.0 and wanted:
        state["armed"] = True
    state["prev_target"] = float(target)

    if wanted == in_position:
        return  # 状态一致，无事可做
    # 说明：实盘对分数目标的处理是工程简化——>0 视为持有态（买入金额按比例缩放），
    # =0 清仓；已持仓期间调整比例不会触发调仓（要改比例请先手动卖出）。

    if wanted and not in_position:
        if not state.get("armed", True):  # 止损后锁仓：等新的跳变才放行
            logger.info(f"{symbol} 止损后锁仓中，等待新的金叉跳变才重新入场")
            return
        spend = quote_per_trade * float(target)  # 分数目标按比例缩放投入
        amount = spend / price
        if not order_enabled:
            logger.info(f"[模拟] 将市价买入 {amount:.6f} {base}（约 {spend:.0f} USDT）")
            return
        # 余额差值记账：买入前后各拍一次可用余额快照，差额=实际到手（自动消化
        # 部分成交和"手续费以基础币收取"两类偏差，比信订单名义数量可靠）
        before = get_free_balance(exchange, symbol)
        order = exchange.create_market_buy_order(symbol, exchange.amount_to_precision(symbol, amount))
        time.sleep(2)  # 给成交与余额结算留一点时间
        after = get_free_balance(exchange, symbol)
        got = max(after - before, 0.0)
        if got <= 0:
            # 单已提交却读不到余额变化：宁可少记不能多记（多记会让止损线失真、
            # 卖出超额），下轮对账告警会兜底提示
            logger.warning("买入单已提交但未读到余额变化，账本本轮不更新（下轮对账会提示）")
            save_state(STATE_FILE, state)
            return
        new_base = bot_holding + got
        # 持仓均价用"实际花费加权"（金额×现价≈真实支出），供止损判断；不能用
        # 名义 quote_per_trade——分数仓位时那会高估成本、让止损线提前触发
        old_cost = float(entry_price or 0.0) * bot_holding
        state["entry_price"] = (old_cost + amount * price) / new_base
        state["bot_base"] = round(new_base, 8)
        save_state(STATE_FILE, state)
        logger.info(f"[成交] 买入单 id={order.get('id')}，实际入账 {got:.6f} {base}")
        send_text("🤖 机器人买入", f"{symbol} 金叉信号，市价买入约 {spend:.0f} USDT"
                                  f"（到手 {got:.6f} {base}）")
    elif in_position and not wanted:
        free_now = get_free_balance(exchange, symbol)
        sell_amount = min(bot_holding, free_now)
        if sell_amount * price < min_notional(exchange, symbol):
            # 低于交易所最小下单额的灰尘永远卖不掉——重试只会死循环。标记关账，留下零头
            logger.warning(f"机器人持仓市值 {sell_amount * price:.2f} USDT 低于交易所最小下单额，"
                           f"按灰尘弃置并清零账本（零头留在账户里）")
            state["bot_base"] = 0.0
            state["entry_price"] = None
            save_state(STATE_FILE, state)
            return
        order = exchange.create_market_sell_order(symbol, exchange.amount_to_precision(symbol, sell_amount))
        time.sleep(2)
        after = get_free_balance(exchange, symbol)
        sold = max(free_now - after, 0.0)  # 余额差值记账（与买入路径对称）
        state["bot_base"] = round(max(bot_holding - sold, 0.0), 8)
        if state["bot_base"] <= 1e-12:  # 清仓：止损基准一并失效
            state["entry_price"] = None
        save_state(STATE_FILE, state)
        logger.info(f"[成交] 卖出单 id={order.get('id')}，实际卖出 {sold:.6f} {base}")
        send_text("🤖 机器人卖出", f"{symbol} 死叉信号，市价卖出 {sold:.6f} {base}")


# ---------------------------------------------------------------- 主循环

def fmt_timeframe_seconds(timeframe: str) -> int:
    """把 '1h' 之类换算成秒。非法周期直接给中文报错（而不是 KeyError traceback）。"""
    if timeframe not in VALID_TIMEFRAMES:
        raise ValueError(f"非法K线周期 {timeframe!r}，可选：{' '.join(sorted(VALID_TIMEFRAMES))}")
    unit = timeframe[-1]
    n = int(timeframe[:-1])
    return n * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


def maybe_heartbeat(state: dict, exchange, symbol: str, mode: str, logger) -> None:
    """每天第一条日志后向微信发一次"我还活着"——收不到心跳 = 机器人可能挂了。"""
    today = date.today().isoformat()
    if state.get("last_heartbeat") == today:
        return
    state["last_heartbeat"] = today
    save_state(STATE_FILE, state)
    try:
        price = float(exchange.fetch_ticker(symbol)["last"])
        body = f"模式: {mode}\n{symbol} 最新价: {price:.2f}\n机器人持仓: {state.get('bot_base', 0.0)}"
    except Exception as exc:
        body = f"模式: {mode}（行情获取失败，仅心跳：{exc}）"
    send_text("💓 机器人每日心跳", body)


def main() -> None:
    parser = argparse.ArgumentParser(description="币安双均线实盘机器人")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h", help="信号K线周期: 15m/1h/4h/1d")
    parser.add_argument("--fast", type=int, default=20)
    parser.add_argument("--slow", type=int, default=60)
    parser.add_argument("--quote-per-trade", type=float,
                        default=config.get_float("QUOTE_PER_TRADE", 50.0),
                        help="每次买入花费的 USDT 金额")
    parser.add_argument("--poll", type=int, default=60, help="轮询间隔（秒），最低 30")
    parser.add_argument("--live", action="store_true", help="不加此参数=纯模拟(dry-run)")
    parser.add_argument("--real", action="store_true", help="真钱三重确认之二：还需输入确认短语")
    parser.add_argument("--stop-loss", type=float, default=None, dest="stop_loss",
                        help="止损比例，如 0.05=从持仓均价亏5%%触发市价卖出（默认不启用，见第8章）")
    args = parser.parse_args()

    logger = setup_logging()
    if args.slow <= args.fast:
        logger.error(f"慢线窗口({args.slow})必须大于快线({args.fast})")
        return
    if args.stop_loss is not None and not (0.0 < args.stop_loss < 1.0):
        logger.error(f"--stop-loss 应为 0~1 之间的小数（如 0.05 = 5%），收到 {args.stop_loss}")
        return
    tf_sec = fmt_timeframe_seconds(args.timeframe)  # 非法周期在这里就以中文报错退出
    poll = max(args.poll, 30)

    exchange, sandbox = make_exchange()
    # 缺密钥判断要跟所配交易所对上（EXCHANGE_ID=okx 时看 OKX 的 key，不是币安的）
    has_keys = bool(config.get(api_key_name(config.exchange_id())))
    order_enabled, mode = resolve_mode(args.live, args.real, sandbox, has_keys)

    logger.info(f"当前模式: {mode}" + (f" | 止损: {args.stop_loss:.0%}" if args.stop_loss else ""))
    real_money = order_enabled and not sandbox
    if real_money:
        # 真钱合规确认门（F4 决议）：技术门禁替代人性自觉
        print("\n⚠️  真实资金模式。加密货币交易在大陆的合规与冻卡风险见 docs/09 第 9.2 节。")
        ans = input(f"确认你已阅读并接受全部风险，请输入确认短语 {REAL_MONEY_PHRASE}：").strip()
        if ans != REAL_MONEY_PHRASE:
            logger.error("确认短语不匹配，退出。真钱需要 --live --real 并手动输入确认短语")
            return
        logger.warning("!!! 真实资金模式 !!! 任何错误都会造成真实亏损。Ctrl+C 可随时退出")
        time.sleep(5)

    state = load_state(STATE_FILE)
    warned: dict = {}
    logger.info(f"启动: {args.symbol} MA{args.fast}x{args.slow}@{args.timeframe} "
                f"每笔 {args.quote_per_trade} USDT | 轮询 {poll}s | 信号周期 {tf_sec}s")

    import ccxt  # 延迟导入：只在此处用于异常分类

    while True:
        try:
            run_once(exchange, args.symbol, args.timeframe, args.fast, args.slow,
                     args.quote_per_trade, order_enabled, state, warned, logger,
                     stop_loss_pct=args.stop_loss)
            maybe_heartbeat(state, exchange, args.symbol, mode, logger)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            # 错误分诊（Eng M9）：永久性错误重试没有意义，必须停下来叫人。
            # 用 isinstance 而非异常类名字符串——子类能命中，ccxt 改名也不会静默失效
            if isinstance(exc, (ccxt.AuthenticationError, ccxt.PermissionDenied,
                                ccxt.AccountSuspended)):
                logger.error(f"致命错误：API Key 无效或无权限。停机。{exc}")
                send_text("🛑 机器人停机",
                          f"鉴权失败（{type(exc).__name__}），已停止。请检查 API Key 权限与 IP 白名单")
                break
            if isinstance(exc, (ccxt.InsufficientFunds, ccxt.InvalidOrder,
                                ccxt.BadSymbol, ccxt.ArgumentsRequired)):
                logger.error(f"永久性错误：重试无意义，停机排查。{exc}")
                send_text("🛑 机器人停机",
                          f"订单被拒绝（{type(exc).__name__}）：{exc}\n常见原因：金额低于最小下单额/代码写错")
                break
            # 网络抖动/限流等瞬时错误：记日志，下一轮再试
            logger.error(f"瞬时错误（{type(exc).__name__}），下一轮重试: {exc}")
        try:
            time.sleep(poll)
        except KeyboardInterrupt:
            break  # 睡眠期按 Ctrl+C 也要退出（此前 pass 会吞掉按键，机器人"按不住"）


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，机器人已干净退出")
