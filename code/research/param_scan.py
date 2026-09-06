# -*- coding: utf-8 -*-
"""
第 7 章配套脚本：参数网格扫描 —— 找出"哪组参数最好"，同时警惕过拟合。

用法（项目根目录）：
    python code/research/param_scan.py --astock 510300
    python code/research/param_scan.py --astock 510300 --fast 10,15,20,25,30 --slow 40,60,80,100

它会：
    1. 下载数据，遍历 fast×slow 所有组合，各跑一次回测
    2. 打印一张"参数 × 指标"的热力图（ASCII 表格）
    3. 标出最优/最差参数，并给出过拟合警示
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch03_data import datasource  # noqa: E402
from ch04_backtest.engine import run_backtest  # noqa: E402
from ch04_backtest.strategy import dual_ma_weights  # noqa: E402

# 展示为百分比的两个指标（其余按浮点展示）
PCT_METRICS = {"总收益率", "年化收益率(CAGR)", "最大回撤"}


def _parse_ints(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def _fmt(metric: str, val: float) -> str:
    if pd.isna(val):
        return "--".rjust(10)
    if metric in PCT_METRICS:
        return f"{val:>10.1%}"
    return f"{val:>10.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="双均线参数网格扫描")
    parser.add_argument("--astock", default="510300", help="A股/ETF代码")
    parser.add_argument("--fast", default="5,10,15,20,30,40", help="快线候选，逗号分隔")
    parser.add_argument("--slow", default="40,60,80,100,120", help="慢线候选，逗号分隔")
    parser.add_argument("--metric", default="总收益率",
                        choices=["总收益率", "夏普比率", "最大回撤", "年化收益率(CAGR)"],
                        help="热力图展示的指标")
    args = parser.parse_args()

    fasts = _parse_ints(args.fast)
    slows = _parse_ints(args.slow)
    metric = args.metric
    lower_better = metric == "最大回撤"

    print(f"[数据] 下载 {args.astock} ...")
    df = datasource.fetch_daily_with_cache(args.astock)
    print(f"[数据] {args.astock}: {df.index[0].date()} ~ {df.index[-1].date()}，共 {len(df)} 根K线\n")

    rows: dict[int, dict[int, float]] = {}
    best_val = float("inf") if lower_better else -float("inf")
    worst_val = -float("inf") if lower_better else float("inf")
    best_key = worst_key = None

    for fast in fasts:
        rows[fast] = {}
        for slow in slows:
            if slow <= fast:  # 慢线必须大于快线，否则无意义
                rows[fast][slow] = float("nan")
                continue
            r = run_backtest(df, dual_ma_weights(df, fast, slow), with_benchmark=False)
            val = r.stats.get(metric, float("nan"))
            rows[fast][slow] = val
            if pd.isna(val):
                continue
            if (val < best_val) if lower_better else (val > best_val):
                best_val, best_key = val, (fast, slow)
            if (val > worst_val) if lower_better else (val < worst_val):
                worst_val, worst_key = val, (fast, slow)

    print(f"指标：{metric}（{'越小越好' if lower_better else '越大越好'}）\n")
    header = "fast\\slow" + "".join(f"{s:>10d}" for s in slows)
    print(header)
    print("-" * len(header))
    for fast in fasts:
        line = f"{fast:>9d}"
        for slow in slows:
            line += _fmt(metric, rows[fast][slow])
        print(line)

    if best_key:
        print(f"\n最优参数: MA{best_key[0]}xMA{best_key[1]}，{metric} = {_fmt(metric, best_val).strip()}")
        print(f"最差参数: MA{worst_key[0]}xMA{worst_key[1]}，{metric} = {_fmt(metric, worst_val).strip()}")

    print("\n[过拟合警示] 盯着这张热力图问自己三个问题：")
    print("  ① 最优参数是不是'孤岛'？——若只有 MA20x60 好，旁边 MA15x60 / MA25x60 都很差，")
    print("     这个'最优'极可能是运气，实盘大概率失效。")
    print("  ② 是一大片区域都好，还是只有一点好？——前者才说明策略有真逻辑（参数稳健）。")
    print("  ③ 你是不是反复调参、调到这张表'好看'为止？——每调一次就多偷看一次答案，")
    print("     这张表就被你'用旧'了。真正的验证请看 walkforward.py（样本外）。")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n[出错] {exc}")
        print("[下一步] 网络类报错等 1~5 分钟重试；数据会自动用本地缓存 data/*.csv")
        sys.exit(1)
