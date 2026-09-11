# -*- coding: utf-8 -*-
"""
第 3 章配套脚本：生成固定种子的样例 K 线数据（离线体验用）。

为什么要有假数据？
  免费接口会限流、断网、维护——但学习回测不应该被网络卡住。
  固定随机种子（seed=42）意味着：任何人、任何电脑、任何时候重新生成，
  得到的数据都【逐行一致】——文档里的"预期输出"因此可以逐位对照复现。

用法（项目根目录）：
    python code/ch03_data/make_sample_data.py                  # 生成 data/sample_prices.csv
    python code/ch03_data/make_sample_data.py --rows 500       # 自定义根数
之后即可离线回测：
    python code/ch04_backtest/run_dual_ma.py --csv data/sample_prices.csv --no-plot
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch03_data import datasource  # noqa: E402


def make_sample_ohlcv(rows: int = 250, seed: int = 42) -> pd.DataFrame:
    """
    固定种子生成 OHLCV 日线：几何随机游走（日收益均值 0.05%、波动 1.5%）。

    open 围绕前收盘小幅跳动，high/low 按 max/min(open, close) 向外扩噪声影线，
    保证 low <= min(open, close) <= max(open, close) <= high（合法 K 线形态）。
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=rows)  # 工作日日线（无周末 -> 年化按 252）
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.015, rows))
    open_ = close * (1.0 + rng.normal(0.0, 0.003, rows))
    body_hi = np.maximum(open_, close)
    body_lo = np.minimum(open_, close)
    spread = np.abs(rng.normal(0.0, 0.004, rows)) + 1e-4  # 影线幅度（恒正，避免高低价重合）
    df = pd.DataFrame({
        "open": open_,
        "close": close,
        "high": body_hi * (1.0 + spread),
        "low": body_lo * (1.0 - spread),
        "volume": rng.integers(8_000, 20_000, rows).astype(float),
    }, index=idx)
    df.index.name = "date"
    df.attrs["symbol"] = "SAMPLE"
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="生成固定种子样例K线（离线回测用）")
    parser.add_argument("--rows", type=int, default=250, help="K线根数（默认 250，够 MA60 跑起来）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子（默认 42，保证逐位可复现）")
    args = parser.parse_args()

    df = make_sample_ohlcv(args.rows, args.seed)
    datasource.save_csv(df, "sample_prices")
    print(f"[样例] {df.index[0].date()} ~ {df.index[-1].date()}，"
          f"close {df['close'].iloc[0]:.2f} -> {df['close'].iloc[-1]:.2f}（种子 {args.seed}）")


if __name__ == "__main__":
    main()
