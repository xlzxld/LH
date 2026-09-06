# -*- coding: utf-8 -*-
"""
第 7 章配套脚本：样本外验证 —— 策略能不能上实盘，这一关说了算。

用法（项目根目录）：
    python code/research/walkforward.py --astock 510300
    python code/research/walkforward.py --astock 510300 --split 0.7 --fast 20 --slow 60

原理（一句话）：
    把历史切成两段：前段"样本内"用来调参（练习册），后段"样本外"锁起来最后验证（考试卷）。
    样本内漂亮、样本外崩了 → 你的参数是背答案背出来的（过拟合），不能上实盘。

使用纪律：
    样本外只能看一次。看完再回去改参数，考试卷就变成练习册，失去验证意义。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch03_data import datasource  # noqa: E402
from ch04_backtest.engine import run_backtest  # noqa: E402
from ch04_backtest.strategy import dual_ma_weights  # noqa: E402


def _fmt_stats(stats: dict) -> str:
    return (f"总收益 {stats.get('总收益率', 0):>8.2%} | 年化 {stats.get('年化收益率(CAGR)', 0):>8.2%} | "
            f"夏普 {stats.get('夏普比率', 0):>6.2f} | 回撤 {stats.get('最大回撤', 0):>8.2%} | "
            f"交易 {stats.get('交易次数', 0)} 次")


def judge_verdict(in_ret: float, out_ret: float, out_trades: int) -> list[str]:
    """
    样本外验证的判定逻辑（纯函数，方便测试）。

    返回判定消息列表，每条对应一个结论。判定规则：
      * 样本外交易次数 < 5 → 结果没有统计意义
      * 样本外收益 >= 0 → 通过第一道关；否则 → 过拟合，不能上实盘
      * 样本内外收益差距 > 20 个百分点 → 策略在"过期"
    """
    msgs: list[str] = []
    if out_trades < 5:
        msgs.append("⚠️ 样本外交易次数太少（<5），结果没有统计意义，建议把 --split 调小、留更多样本外。")
    if out_ret >= 0:
        msgs.append("✅ 样本外仍为正收益，策略通过了第一道关。")
    else:
        msgs.append("❌ 样本外亏损。样本内赚钱、样本外亏钱 = 典型过拟合，这个参数不能上实盘。")
    if abs(out_ret - in_ret) > 0.20:
        msgs.append("⚠️ 样本内外的收益差距超过 20 个百分点，策略在'过期'，需警惕。")
    return msgs


def main() -> None:
    parser = argparse.ArgumentParser(description="双均线样本外验证")
    parser.add_argument("--astock", default="510300")
    parser.add_argument("--split", type=float, default=0.7, help="样本内占比（0~1）")
    parser.add_argument("--fast", type=int, default=20, help="要验证的快线参数")
    parser.add_argument("--slow", type=int, default=60, help="要验证的慢线参数")
    args = parser.parse_args()

    if not 0.3 < args.split < 0.9:
        parser.error("--split 建议在 0.3~0.9 之间")

    print(f"[数据] 下载 {args.astock} ...")
    df = datasource.fetch_daily_with_cache(args.astock)
    cut = int(len(df) * args.split)
    in_df = df.iloc[:cut]
    out_df = df.iloc[cut:]
    print(f"[切分] 样本内 {in_df.index[0].date()}~{in_df.index[-1].date()}（{len(in_df)} 根）")
    print(f"[切分] 样本外 {out_df.index[0].date()}~{out_df.index[-1].date()}（{len(out_df)} 根）\n")
    print(f"验证参数: MA{args.fast}xMA{args.slow}\n")

    r_in = run_backtest(in_df, dual_ma_weights(in_df, args.fast, args.slow), with_benchmark=False)
    r_out = run_backtest(out_df, dual_ma_weights(out_df, args.fast, args.slow), with_benchmark=False)

    print(f"样本内（练习册）: {_fmt_stats(r_in.stats)}")
    print(f"样本外（考试卷）: {_fmt_stats(r_out.stats)}")

    in_ret = r_in.stats.get("总收益率", 0.0)
    out_ret = r_out.stats.get("总收益率", 0.0)
    out_trades = r_out.stats.get("交易次数", 0)

    print("\n" + "=" * 60)
    print("[判定]")
    for msg in judge_verdict(in_ret, out_ret, out_trades):
        print(f"  {msg}")
    print("\n  记住：样本外只能看一次。反复用样本外结果回去改参数，考试卷就变成练习册了。")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n[出错] {exc}")
        print("[下一步] 网络类报错等 1~5 分钟重试；数据会自动用本地缓存 data/*.csv")
        sys.exit(1)
