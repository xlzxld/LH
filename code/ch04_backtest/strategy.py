# -*- coding: utf-8 -*-
"""
策略函数库：本地回测（第4章）与实盘机器人（第9章）共用同一份信号代码。

为什么单独一个模块（Eng 评审架构建议）：
  以前 dual_ma_weights 放在命令行脚本 run_dual_ma.py 里，实盘机器人 import
  一个"脚本"很脆弱（读者一改脚本里的 argparse 就可能弄坏机器人）。
  现在策略、脚本、机器人三者关系是：

      strategy.py（信号，唯一真源）
         ├─→ run_dual_ma.py（回测入口，教学用）
         └─→ live_bot.py   （实盘入口）
"""
from __future__ import annotations

import pandas as pd


def dual_ma_weights(df: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    """
    双均线信号 -> 目标仓位序列（唯一真源，回测与实盘共用）。

    均线用收盘价的滚动平均；慢线窗口不够长的前段返回 NaN。
    NaN 的语义 = "数据不足，维持现状不动"（不是"清仓"！）——
    实盘机器人必须尊重这个契约：遇到 NaN 跳过本轮，绝不反向交易。
    """
    ma_fast = df["close"].rolling(fast).mean()
    ma_slow = df["close"].rolling(slow).mean()
    weights = pd.Series(float("nan"), index=df.index)
    weights[(ma_fast > ma_slow) & ma_slow.notna()] = 1.0  # 金叉状态：满仓
    weights[(ma_fast <= ma_slow) & ma_slow.notna()] = 0.0  # 死叉状态：空仓
    return weights


def sized_weights(weights: pd.Series, fraction: float) -> pd.Series:
    """
    把 0/1 信号缩放成 0~fraction 的仓位：信号为"满仓"时，实际只投入总资金的 fraction。

    这就是第 8 章仓位管理里的"固定比例法"（position_sizing.fixed_fraction）
    在目标仓位上的落地：fraction=0.3 意味着每次最多用 30% 资金，剩下 70%
    永远留作现金缓冲。回测引擎和实盘机器人吃到的 target_weights 只要是
    0~1 的数字即可，所以仓位法可以直接在这里叠加，无需改引擎。

    举例：dual_ma_weights 输出 [1, 0, 1]，sized_weights(..., 0.3) 得到 [0.3, 0, 0.3]。
    NaN 保持不变（数据不足仍是"不动"）。
    """
    if not 0 < fraction <= 1:
        raise ValueError("fraction 应在 (0, 1] 之间")
    return weights * fraction


def dual_ma_weights_sized(df: pd.DataFrame, fast: int, slow: int,
                          fraction: float) -> pd.Series:
    """
    带固定比例仓位的双均线：金叉时目标仓位 = fraction（而非满仓 1.0）。

    与 dual_ma_weights 的唯一区别是仓位大小，信号逻辑完全一致，
    回测（engine）与实盘（live_bot）都已支持非 0/1 的分数目标：
      * engine：持有态(>0)正常建仓到该比例；止损锁仓对分数目标同样生效，
        解锁条件是出现 空仓→持有 的新跳变。
      * live_bot：目标>0 视为持有态（买入金额 = 每笔预算 × fraction），
        目标=0 清仓；注意已持仓期间调整 fraction 不会触发调仓（工程简化，
        要改比例先手动卖出）。
    """
    return sized_weights(dual_ma_weights(df, fast, slow), fraction)
