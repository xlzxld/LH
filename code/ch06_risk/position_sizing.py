# -*- coding: utf-8 -*-
"""
第 8 章配套脚本：仓位管理工具 —— 决定"这一笔到底买多少"。

新手爆仓/深套的头号原因不是策略差，而是仓位乱。这里实现四种经典仓位法：
  1. fixed_amount   固定金额：每笔固定花 1 万元，最简单，推荐起步用
  2. fixed_fraction 固定比例：每笔投入总资金的固定百分比
  3. atr_risk       波动倒推：单笔最多亏总资金的 R%，按波动率倒推仓位（专业做法）
  4. kelly          凯利公式：按胜率和盈亏比算最优比例（打对折用，即"半凯利"）

用法：
    python code/ch06_risk/position_sizing.py --method fixed_fraction --equity 100000 --fraction 0.2
    python code/ch06_risk/position_sizing.py --method atr_risk --equity 100000 --risk-pct 0.01 --atr 0.015
    python code/ch06_risk/position_sizing.py --method kelly --equity 100000 --win-rate 0.4 --win-loss-ratio 2.0
注意：--risk-pct 与 --atr 都是"小数"——0.01 表示 1%。填成 1 就是 100%，语义全错。
"""
from __future__ import annotations

import argparse


def fixed_amount(equity: float, per_trade: float) -> float:
    """固定金额：每笔固定投入 per_trade 元，但不超过总资金。"""
    return min(per_trade, equity)


def fixed_fraction(equity: float, fraction: float) -> float:
    """固定比例：每笔投入 equity * fraction。常用 10%~30%。"""
    if not 0 < fraction <= 1:
        raise ValueError("fraction 应在 (0, 1] 之间")
    return equity * fraction


def atr_risk(equity: float, risk_pct: float, atr_pct: float) -> float:
    """
    波动倒推法（趋势策略标准做法）：
        允许亏损额 = equity * risk_pct          （比如总资金的 1%）
        仓位市值 = 允许亏损额 / 止损距离百分比
    atr_pct 用标的日均波动幅度近似（如 ETF 0.5%~1.5%、BTC 2%~4%），
    并建议把止损距离设为 2 倍 ATR。
    """
    if atr_pct <= 0:
        raise ValueError("atr_pct 必须为正")
    stop_distance = 2.0 * atr_pct  # 止损距离 = 2 倍日均波动
    return equity * risk_pct / stop_distance


def kelly(win_rate: float, win_loss_ratio: float, halve: bool = True) -> float:
    """
    凯利公式：f* = W - (1-W)/R
    W=胜率，R=平均盈利/平均亏损。注意：凯利给出的是"理论最优"，真实参数估计
    误差很大，所以实践只用"半凯利"甚至"四分之一凯利"。
    """
    if not 0 < win_rate < 1 or win_loss_ratio <= 0:
        raise ValueError("胜率需在 (0,1)，盈亏比需为正")
    f = win_rate - (1 - win_rate) / win_loss_ratio
    f = max(f, 0.0)
    return f / 2 if halve else f


def main() -> None:
    parser = argparse.ArgumentParser(description="仓位计算器")
    parser.add_argument("--method", required=True,
                        choices=["fixed_amount", "fixed_fraction", "atr_risk", "kelly"])
    parser.add_argument("--equity", type=float, help="账户总资金")
    parser.add_argument("--per-trade", type=float, help="fixed_amount: 每笔固定金额")
    parser.add_argument("--fraction", type=float, help="fixed_fraction: 每笔比例，如 0.2")
    parser.add_argument("--risk-pct", type=float, default=0.01, help="atr_risk: 单笔可承受亏损占总资金比例")
    parser.add_argument("--atr", type=float, help="atr_risk: 日均波动幅度，如 0.01 表示 1%%")
    parser.add_argument("--win-rate", type=float, help="kelly: 回测统计的胜率")
    parser.add_argument("--win-loss-ratio", type=float, help="kelly: 回测统计的盈亏比")
    args = parser.parse_args()

    # 每种方法校验自己的必填参数——新手最烦的就是裸 TypeError traceback
    need = {
        "fixed_amount": [("equity", "--equity 总资金"), ("per_trade", "--per-trade 每笔固定金额")],
        "fixed_fraction": [("equity", "--equity 总资金"), ("fraction", "--fraction 每笔比例(如0.2)")],
        "atr_risk": [("equity", "--equity 总资金"), ("atr", "--atr 日均波动幅度(如0.01)")],
        "kelly": [("equity", "--equity 总资金"), ("win_rate", "--win-rate 胜率"),
                  ("win_loss_ratio", "--win-loss-ratio 盈亏比")],
    }[args.method]
    for attr, hint in need:
        if getattr(args, attr) is None:
            parser.error(f"方法 {args.method} 需要参数 {hint}")
    # 总资金必须为正：否则最后算"占总资金比例"时会抛裸 ZeroDivisionError，
    # 让新手看到一串看不懂的 traceback，而不是看得懂的中文提示
    if args.equity <= 0:
        parser.error(f"--equity 必须为正数（收到 {args.equity:g}）。"
                     "它是账户总资金，例如 --equity 100000")

    if args.method == "fixed_amount":
        amount = fixed_amount(args.equity, args.per_trade)
    elif args.method == "fixed_fraction":
        amount = fixed_fraction(args.equity, args.fraction)
    elif args.method == "atr_risk":
        amount = atr_risk(args.equity, args.risk_pct, args.atr)
    else:
        frac = kelly(args.win_rate, args.win_loss_ratio)
        amount = args.equity * frac
        print(f"半凯利仓位比例 = {frac:.2%}")
    print(f"建议本笔投入: {amount:,.0f} 元（占总资金 {amount / args.equity:.1%}）")


if __name__ == "__main__":
    main()
