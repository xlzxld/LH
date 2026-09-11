# -*- coding: utf-8 -*-
"""
第 4 章配套脚本：第一个量化策略 —— 双均线择时，完整跑一次回测。

策略逻辑（最容易理解的入门策略）：
    短期均线(MA快线)上穿长期均线(MA慢线) -> 满仓（金叉买入）
    短期均线下穿长期均线(MA慢线) -> 空仓 （死叉卖出）

用法（项目根目录）：
    python code/ch04_backtest/run_dual_ma.py                        # 默认: 510300 沪深300ETF
    python code/ch04_backtest/run_dual_ma.py --astock 512100 --fast 20 --slow 60
    python code/ch04_backtest/run_dual_ma.py --crypto BTC/USDT --timeframe 1d
    python code/ch04_backtest/run_dual_ma.py --execute-on close     # 体验"未来函数"的乐观偏差
    python code/ch04_backtest/run_dual_ma.py --stop-loss 0.05       # 加 5% 止损（见第 8 章）
    python code/ch04_backtest/run_dual_ma.py --astock 000001 --stamp-duty 0.0005
                                                    # 跑A股个股：卖出印花税别漏（ETF/币安免税不用加）
    python code/ch04_backtest/run_dual_ma.py --csv data/sample_prices.csv --no-plot
                                                    # 完全离线：先跑 code/ch03_data/make_sample_data.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch03_data import datasource  # noqa: E402
from ch04_backtest.engine import run_backtest  # noqa: E402
from ch04_backtest.strategy import dual_ma_weights  # noqa: E402  # 唯一真源：实盘机器人也用它
from ch05_metrics.performance import plot_equity, print_stats  # noqa: E402
import common.config as cfg  # noqa: E402

CRYPTO_MINUTES_PER_YEAR = 365 * 24 * 60  # 加密货币 7×24 全年无休


def crypto_periods(timeframe: str) -> int:
    """
    加密货币的年化基数 = 一年的K线根数（按自然年；A股是 252 个交易日，别搞混）。
    支持分钟/小时/天/周级；认不出的周期按日线(365)保守处理并警告——
    绝不能静默用错口径（5m 错按 365 算会让年化差 200 倍以上）。
    """
    mult = {"m": 1, "h": 60, "d": 1440, "w": 10080}
    try:
        minutes = int(timeframe[:-1]) * mult[timeframe[-1]]
        periods = int(CRYPTO_MINUTES_PER_YEAR / minutes)
    except (ValueError, KeyError):
        print(f"[警告] 未知K线周期 {timeframe!r}，年化基数按日线(365)保守计算")
        return 365
    if periods < 1:  # 周线及以上
        print(f"[警告] K线周期 {timeframe!r} 长于一周，年化基数按 52（周线）保守计算")
        return 52
    return periods


def _load_local_csv(path: str) -> pd.DataFrame:
    """
    读取本地 CSV 离线回测（--csv 参数）：首列/date 列解析为日期索引。
    缺文件、缺列都在第一时间给中文友好报错，而不是让新手面对 pandas 裸异常。
    """
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"找不到 CSV 文件: {csv_path}"
            "（想离线体验可先运行 python code/ch03_data/make_sample_data.py 生成样例数据）")
    df = pd.read_csv(csv_path, encoding="utf-8-sig", index_col=0, parse_dates=True)
    missing = {"open", "close"} - set(df.columns)
    if missing:
        raise ValueError(f"CSV 缺少列: {sorted(missing)}，实际列: {list(df.columns)}"
                         "（离线回测至少需要 open/close 两列，日期放在第一列）")
    df.index.name = "date"
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="双均线策略回测")
    parser.add_argument("--astock", default="510300", help="A股/ETF代码")
    parser.add_argument("--crypto", help="改用加密货币，如 BTC/USDT")
    parser.add_argument("--csv", help="离线数据源：本地CSV路径（优先级最高，提供后跳过网络）")
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--start", default="20180101")
    parser.add_argument("--end", default="20500101")
    parser.add_argument("--fast", type=int, default=20, help="快线窗口")
    parser.add_argument("--slow", type=int, default=60, help="慢线窗口")
    parser.add_argument("--cash", type=float, default=cfg.get_float("INITIAL_CASH", 100_000),
                        help="初始资金（默认读 .env 的 INITIAL_CASH）")
    parser.add_argument("--commission", type=float, default=cfg.get_float("COMMISSION_RATE", 2.5e-4),
                        help="单边手续费率（默认读 .env 的 COMMISSION_RATE）")
    parser.add_argument("--min-fee", type=float, default=0.0, help="每笔最低佣金（A股券商约5元）")
    parser.add_argument("--stamp-duty", type=float, default=0.0,
                        help="卖出印花税率：A股个股 0.0005；ETF/加密货币免收保持 0")
    parser.add_argument("--slippage", type=float, default=cfg.get_float("SLIPPAGE_RATE", 5e-4),
                        help="单边滑点率（默认读 .env 的 SLIPPAGE_RATE）")
    parser.add_argument("--stop-loss", type=float, default=None,
                        help="止损比例，如 0.05=亏5%%触发（默认不启用，见第8章）")
    parser.add_argument("--execute-on", default="next_open", choices=["close", "next_open"])
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()

    # ---- 1. 取数据
    periods = None  # 交给引擎按日历自动推断（含周末→365，A股→252）
    if args.csv:
        df = _load_local_csv(args.csv)
        name = Path(args.csv).stem
        source = "本地CSV"
    elif args.crypto:
        df = datasource.fetch_crypto_ohlcv(args.crypto, timeframe=args.timeframe, limit=1000)
        name = args.crypto.replace("/", "")  # 斜杠不能出现在文件名里
        if len(df) > 1:  # 最后一根K线尚未收盘，拿它算信号就是"未来函数"——剔掉
            df = df.iloc[:-1]
        periods = crypto_periods(args.timeframe)
        source = f"{args.crypto}"
    else:
        df = datasource.fetch_daily_with_cache(args.astock, start=args.start, end=args.end)
        name = args.astock
        source = f"东财接口 {name}"
    print(f"\n[数据] {source}: {df.index[0].date()} ~ {df.index[-1].date()}，共 {len(df)} 根K线"
          + ("（已剔除最后一根未收盘K线）" if args.crypto else ""))

    # ---- 2. 生成信号
    weights = dual_ma_weights(df, args.fast, args.slow)

    # ---- 3. 回测
    result = run_backtest(
        df, weights,
        initial_cash=args.cash,
        commission_rate=args.commission,
        min_fee=args.min_fee,
        stamp_duty_rate=args.stamp_duty,
        slippage_rate=args.slippage,
        execute_on=args.execute_on,
        stop_loss_pct=args.stop_loss,
        periods_per_year=periods,
    )

    # ---- 4. 看结果
    print(f"\n策略参数: MA{args.fast} x MA{args.slow} | 成交方式: {args.execute_on}"
          + (f" | 止损: {args.stop_loss:.0%}" if args.stop_loss else ""))
    print_stats(result.stats)

    cfg.ensure_dirs()
    trades_path = cfg.OUTPUT_DIR / f"dual_ma_{name}_trades.csv"
    pd.DataFrame(result.trades).to_csv(trades_path, index=False, encoding="utf-8-sig")
    print(f"[流水] 成交记录已保存: {trades_path}")

    if not args.no_plot:
        plot_equity(
            result.equity, result.benchmark,
            save_path=cfg.OUTPUT_DIR / f"dual_ma_{name}.png",
            title=f"双均线 MA{args.fast}x{args.slow} @ {name}",
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # 新手第一跑最常见的失败是网络/数据问题——把"下一步怎么办"直接送到眼前
        print(f"\n[出错] {exc}")
        print("[下一步] ① 若是网络类报错：等 1~5 分钟再试（免费接口限流很常见），"
              "已下载过的数据会自动用本地缓存 data/*.csv")
        print("         ② 若提示缺少 xxx 模块：pip install -r requirements.txt")
        print("         ③ 想完全离线体验：先运行 python code/ch03_data/make_sample_data.py，"
              "再加 --csv data/sample_prices.csv")
        print("         ④ 更多排查思路见 docs/13-常见问题FAQ与进阶路线.md")
        sys.exit(1)
