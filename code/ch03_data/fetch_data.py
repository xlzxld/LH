# -*- coding: utf-8 -*-
"""
第 3 章配套脚本：把行情数据下载成 CSV，为回测和监测做准备。

用法（在项目根目录运行）：
    python code/ch03_data/fetch_data.py --astock 510300            # A股/ETF 日线
    python code/ch03_data/fetch_data.py --crypto BTC/USDT          # 币安 BTC 日线
    python code/ch03_data/fetch_data.py --crypto BTC/USDT --timeframe 1h --limit 500
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch03_data.datasource import fetch_crypto_ohlcv, fetch_eastmoney_daily, save_csv  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="下载行情数据保存为 CSV")
    parser.add_argument("--astock", help="A股/ETF 6位代码，如 510300")
    parser.add_argument("--crypto", help="加密货币对，如 BTC/USDT")
    parser.add_argument("--start", default="20180101", help="A股起始日 YYYYMMDD")
    parser.add_argument("--end", default="20500101", help="A股结束日 YYYYMMDD")
    parser.add_argument("--timeframe", default="1d", help="加密货币K线周期: 1h/4h/1d")
    parser.add_argument("--limit", type=int, default=1000, help="加密货币拉取根数")
    args = parser.parse_args()

    if not args.astock and not args.crypto:
        parser.error("至少指定 --astock 或 --crypto 之一")

    if args.astock:
        df = fetch_eastmoney_daily(args.astock, start=args.start, end=args.end)
        print(df.tail(3))
        save_csv(df, f"astock_{args.astock}")

    if args.crypto:
        df = fetch_crypto_ohlcv(args.crypto, timeframe=args.timeframe, limit=args.limit)
        print(df.tail(3))
        fname = args.crypto.replace("/", "") + ("" if args.timeframe == "1d" else f"_{args.timeframe}")
        save_csv(df, f"crypto_{fname}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n[出错] {exc}")
        print("[下一步] ① 网络类报错：等 1~5 分钟再试（免费接口限流很常见）")
        print("         ② 提示缺少模块：pip install -r requirements.txt")
        print("         ③ 币安数据连不上：见 docs/03 第 3.5 节的网络说明")
        sys.exit(1)
