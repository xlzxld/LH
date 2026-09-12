# -*- coding: utf-8 -*-
"""
第 10 章配套脚本：A 股/ETF 监测机器人 —— 自动盯盘，微信推送信号，人工手动下单。

为什么 A 股不自动下单？
    1. 合规与资金安全：个人程序直连券商下单需要专门通道（如 QMT/MiniQMT），门槛高；
    2. 新手阶段"信号 -> 人工确认 -> 手动下单"能强制你复核每一笔交易，是最好的风控。

监测规则（在 .env 里用 WATCHLIST 和 RULES 配置）：
    WATCHLIST=etf:510300,etf:512100,stock:600519     # 监测哪些标的
    MA_FAST=20 / MA_SLOW=60                          # 均线金叉/死叉参数
    BREAKOUT_DAYS=60                                 # 创 60 日新高提醒
    DRAWDOWN_PCT=10                                  # 从 60 日高点回撤 10% 风险提醒
    ALERT_COOLDOWN_DAYS=3                            # 同类事件提醒的冷却天数（防轰炸）

三种运行方式：
    python code/ch08_monitor/monitor_astock.py --once          # 检查一次，只在有新信号时推送
    python code/ch08_monitor/monitor_astock.py --once --force  # 忽略去重，强制推送完整晨报
    python code/ch08_monitor/monitor_astock.py --loop          # 常驻循环，只在交易时段检查

可靠性设计（Eng 评审 1f/M1 的结论）：
    * 盘中"今天的K线还没走完"，金叉可能在收盘前消失——所以盘中信号一律用
      【已收盘】的K线计算，收盘后（15:05 起）才纳入当日 bar。
    * 微信推送【成功】后才记录去重状态：推送失败时信号不丢，下轮重发。
    * "无信号"绝不推送（免费推送渠道的配额很珍贵）——想知道还活着，看 --force 晨报。
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, date, time as dtime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch03_data import datasource  # noqa: E402
from ch04_backtest.strategy import dual_ma_weights  # noqa: E402
from common import config  # noqa: E402
from common.notify import ensure_utf8_stdio, send_text  # noqa: E402
from common.state import load_state, save_state  # noqa: E402

STATE_FILE = config.STATE_DIR / "monitor_state.json"

# 交易时段（北京时间；机器时区需为北京时间，VPS 时区设置见第 12 章）
MORNING = (dtime(9, 35), dtime(11, 30))
AFTERNOON = (dtime(13, 0), dtime(15, 5))  # 15:05 后当日K线视为已收盘，可纳入信号
COOLDOWN_PREFIXES = ("breakout", "dd")  # 事件型规则（非状态翻转）适用冷却期


# ================================================================ 信号规则

def parse_watchlist(override: str | None = None) -> list[str]:
    """把 'etf:510300,stock:600519' 解析成代码列表（--codes 参数可覆盖 .env）。"""
    raw = override if override else config.get("WATCHLIST", "etf:510300")
    result = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        code = item.split(":", 1)[1] if ":" in item else item
        result.append(code)
    return result


def signal_frame(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """
    返回用于算信号的K线：盘中（当日 bar 未收盘）剔除最后一根，
    收盘后（15:05 起）纳入全部。防止"10 点假金叉推出去、收盘又收回"的不可撤回推送。
    """
    if not df.empty and df.index[-1].date() == now.date() and now.time() < AFTERNOON[1]:
        return df.iloc[:-1]
    return df


def check_signals(df: pd.DataFrame, code: str) -> list[dict]:
    """
    对单个标的（已收盘K线）计算所有规则，返回触发的信号列表。
    每条信号: {rule, direction, key, note}

    规则1（均线金叉/死叉）不在此处手写均线，而是复用唯一真源
    ``ch04_backtest.strategy.dual_ma_weights``——保证监测、回测、实盘
    三处的信号语义永远一致。
    """
    signals: list[dict] = []
    if len(df) < 10:
        return signals

    close = df["close"]
    last_date = df.index[-1].date()
    last_price = float(close.iloc[-1])

    # ---- 规则1：均线金叉/死叉（状态机：只在状态变化的当天发一次）
    # 信号语义唯一真源 = ch04_backtest.strategy.dual_ma_weights（回测 / 实盘 / 监测三方共用），
    # 消除此前第三份手写实现——改信号语义时三处不会各自漂移（TODOS #0）
    fast_n = config.get_int("MA_FAST", 20)
    slow_n = config.get_int("MA_SLOW", 60)
    if len(df) >= slow_n + 1:
        weights = dual_ma_weights(df, fast_n, slow_n)
        # 目标仓位 >0 即"快线在慢线上方"；NaN（慢线未就绪）参与比较为 False，
        # 与旧实现 `ma_fast > ma_slow`（NaN 得 False）语义完全一致
        state_today = bool(weights.iloc[-1] > 0)
        state_yesterday = bool(weights.iloc[-2] > 0)
        if state_today and not state_yesterday:
            signals.append({"rule": "均线金叉", "direction": "买入参考",
                            "key": f"ma_gold_{last_date}",
                            "note": f"MA{fast_n} 上穿 MA{slow_n}，趋势转多"})
        elif not state_today and state_yesterday:
            signals.append({"rule": "均线死叉", "direction": "卖出参考",
                            "key": f"ma_dead_{last_date}",
                            "note": f"MA{fast_n} 下穿 MA{slow_n}，趋势转空"})

    # ---- 规则2：创 N 日新高（事件型，有冷却期）
    n_break = config.get_int("BREAKOUT_DAYS", 60)
    if len(df) >= n_break + 1 and last_price > float(df["high"].iloc[-(n_break + 1):-1].max()):
        signals.append({"rule": f"创{n_break}日新高", "direction": "趋势提醒",
                        "key": f"breakout_{last_date}",
                        "note": f"现价 {last_price:.3f} 突破前 {n_break} 日高点"})

    # ---- 规则3：从近期高点回撤超阈值（事件型，有冷却期）
    dd_pct = config.get_float("DRAWDOWN_PCT", 10.0)
    n_dd = config.get_int("DRAWDOWN_DAYS", 60)
    if len(df) >= n_dd:
        recent_high = float(close.iloc[-n_dd:].max())
        drawdown = (last_price / recent_high - 1.0) * 100
        if drawdown <= -dd_pct:
            signals.append({"rule": "回撤提醒", "direction": "风险提醒",
                            "key": f"dd_{last_date}",
                            "note": f"距 {n_dd} 日高点 {recent_high:.3f} 已回撤 {abs(drawdown):.1f}%（阈值 {dd_pct}%）"})
    return signals


# ================================================================ 去重与冷却

def pick_new(code: str, signals: list[dict], state: dict) -> list[dict]:
    """
    挑出"没发过"的信号（不修改状态——推送成功后才 commit）。
    事件型规则（新高/回撤）带冷却期：同类提醒 N 天内不重复轰炸。
    """
    sent: dict = state.get(code, {}).get("sent", {})
    cooldown = config.get_int("ALERT_COOLDOWN_DAYS", 3)
    today = date.today()
    fresh: list[dict] = []
    for s in signals:
        if s["key"] in sent:
            continue
        prefix = s["key"].split("_", 1)[0]
        if prefix in COOLDOWN_PREFIXES:
            recently = False
            for key, day in sent.items():
                if not key.startswith(prefix + "_"):
                    continue
                try:
                    if (today - date.fromisoformat(str(day))).days < cooldown:
                        recently = True
                        break
                except ValueError:
                    continue
            if recently:
                continue
        fresh.append(s)
    return fresh


def commit(code: str, fresh: list[dict], state: dict) -> None:
    """推送成功后才调用：把已发信号的键记入状态（每标的最多留 50 条历史）。"""
    sent = state.setdefault(code, {}).setdefault("sent", {})
    today = date.today().isoformat()
    for s in fresh:
        sent[s["key"]] = today
    # 按记录日期值排序截断: 曾按键名字典序 —— ma_* 排在 breakout_*/dd_* 前面,
    # ma 类记录一多会把较新的冷却记录挤出窗口, 导致信号重复推送
    state[code]["sent"] = dict(sorted(sent.items(), key=lambda kv: kv[1])[-50:])


# ================================================================ 主流程

def in_trading_hours(now: datetime) -> bool:
    """是否在 A 股交易时段（周末不交易；节假日靠行情数据自然为平盘，影响不大）。"""
    if now.weekday() >= 5:
        return False
    t = now.time()
    return MORNING[0] <= t <= MORNING[1] or AFTERNOON[0] <= t <= AFTERNOON[1]


def run_check(force: bool = False, codes_override: str | None = None) -> None:
    """执行一轮检查：拉数据 -> 算信号 -> 去重 -> 组装消息 -> 推送成功才落状态。"""
    ensure_utf8_stdio()  # 消息文案含 emoji：Windows GBK 控制台需先切 UTF-8 输出
    codes = parse_watchlist(codes_override)
    state = load_state(STATE_FILE)
    report_lines: list[str] = []
    trigger_lines: list[str] = []
    pending: list[tuple[str, list[dict]]] = []  # (code, fresh_signals) 待推送成功后落账
    now = datetime.now()

    quotes = None
    try:  # 实时快照可能偶发失败，不应中断监测
        quotes = datasource.fetch_realtime_quotes(codes)
    except Exception as exc:
        print(f"[警告] 实时快照获取失败: {exc}")

    for code in codes:
        try:
            df = datasource.fetch_daily_with_cache(code, start=config.get("LOOKBACK_START", "20240101"))
        except Exception as exc:
            print(f"[错误] {code} 日线获取失败: {exc}")
            continue
        time.sleep(1.0)  # 免费接口要礼貌：请求间隔 1 秒，降低被限流概率

        from_cache = bool(df.attrs.get("from_cache"))
        has_quote = quotes is not None and not quotes.empty and code in quotes.index
        name = str(quotes.loc[code, "名称"]) if has_quote else code
        daily_close = float(df["close"].iloc[-1])
        # 东财快照对停牌/异常标的返回 "-" 字符串: 曾直接 float() 抛 ValueError,
        # 且不在捕获区内, 整轮监测当天崩溃(cron 调度下所有标的都不再检查)。
        # to_numeric 强转 NaN, 落到下方回退逻辑用日线收盘价。
        live_price = pd.to_numeric(quotes.loc[code, "最新价"], errors="coerce") if has_quote else None
        if live_price is not None and not pd.isna(live_price) and live_price > 0:
            price = float(live_price)  # 盘中推"昨日收盘"当现价会误导人，优先实时快照
        else:
            price = daily_close
        as_of = f"，数据截至 {df.index[-1].date()}" + ("（本地缓存）" if from_cache else "")
        report_lines.append(f"- **{name}({code})** 现价 {price:.3f}{as_of}")

        sig_df = signal_frame(df, now)
        fresh = pick_new(code, check_signals(sig_df, code), state)
        for s in fresh:
            trigger_lines.append(f"- 🔔 **{name}({code})** [{s['direction']}] {s['rule']}：{s['note']}")
        if fresh:
            pending.append((code, fresh))

    if not trigger_lines and not force:
        print(f"[完成] {now:%H:%M:%S} 无新信号，不推送（推送 --force 晨报可强制）。标的数={len(codes)}")
        return

    title = "📈 A股监测晨报" if force else "🔔 A股交易信号"
    body = f"**时间：{now:%Y-%m-%d %H:%M}**\n\n"
    if trigger_lines:
        body += "**触发的信号（请人工确认后手动下单）：**\n" + "\n".join(trigger_lines) + "\n\n"
    else:
        body += "本轮无新信号。\n\n"
    if force:
        body += "**监测列表行情：**\n" + "\n".join(report_lines) + "\n\n"
    body += "\n> ⚠️ 信号仅供参考，非投资建议。下单前请自查：仓位是否超限、是否在止损位。"

    ok = send_text(title, body)
    if ok and pending and not force:
        # 推送成功才落去重状态：失败时信号不丢，下一轮会重发
        for code, fresh in pending:
            commit(code, fresh, state)
        save_state(STATE_FILE, state)
    print(f"[完成] {now:%H:%M:%S} 推送{'成功' if ok else '失败（信号将下轮重发）'} "
          f"信号数={len(trigger_lines)} 标的数={len(codes)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="A股监测 + 微信推送")
    parser.add_argument("--once", action="store_true", help="检查一次后退出（定时任务用）")
    parser.add_argument("--loop", action="store_true", help="常驻循环，只在交易时段检查")
    parser.add_argument("--interval", type=int, default=300, help="循环模式下检查间隔（秒），最低 60")
    parser.add_argument("--force", action="store_true", help="强制推送完整报告（忽略去重，不改状态）")
    parser.add_argument("--codes", default=None, help="临时覆盖监测列表，如 'etf:510300,stock:600519'")
    args = parser.parse_args()

    if args.loop:
        print("进入常驻循环，Ctrl+C 干净退出。非交易时段自动休眠……")
        try:
            while True:
                try:
                    if in_trading_hours(datetime.now()):
                        run_check(codes_override=args.codes)
                    else:
                        print(f"[休眠] 当前非交易时段 {datetime.now():%H:%M:%S}")
                except Exception as exc:
                    print(f"[错误] 本轮检查失败: {exc}")
                time.sleep(max(args.interval, 60))
        except KeyboardInterrupt:
            print("\n已退出")
    else:
        run_check(force=args.force, codes_override=args.codes)


if __name__ == "__main__":
    main()
