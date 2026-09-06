# -*- coding: utf-8 -*-
"""
第 6 章配套模块：信号与因子函数库 —— 把"一个想法"变成"可回测的仓位序列"。

为什么要单独一个文件？
  第 4 章你只会用别人写好的 dual_ma_weights。这一章的目标是学会自己造策略。
  策略的本质只有一句话：**输入历史数据，输出"今天该持有多少仓位"（0~1 的数字）**。

  所以每个函数都遵循同一个契约（和 dual_ma_weights 完全一致）：
    输入 df（含 close 等列的 DataFrame，index 是日期）
    输出 pd.Series（每根K线一个 0~1 的目标仓位；NaN = 数据不足，维持现状不动）

本模块分两类：
  1. 因子函数（*_factor）：把一个想法算成一个"分数"（如过去20天涨了多少、RSI）
  2. 策略函数（*_weights）：把因子转成 0~1 仓位，可直接喂给 engine.run_backtest

想清楚"因子"和"策略"的区别，你就入门了量化研究：
  因子 = "什么特征可能有用"（一个数字）
  策略 = "买什么、什么时候买、买多少"（一整套规则，含仓位和换仓）
"""
from __future__ import annotations

import pandas as pd


# ---------------------------------------------------------------- 因子：把想法变成数字

def roc_factor(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """
    动量因子（Rate of Change）：过去 lookback 天涨了多少。

    想法："最近在涨的东西，接下来大概率继续涨"（趋势惯性）。
    返回每根K线的区间涨跌幅（小数，如 0.05 = 涨了 5%），前 lookback 根为 NaN。
    """
    return df["close"].pct_change(lookback)


def rsi_factor(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    RSI 因子（相对强弱）：取值 0~100，>70 偏超买、<30 偏超卖。

    想法："涨太猛了会回调，跌太狠了会反弹"（均值回归）。
    这是最经典的技术因子，很多策略以它为地基。这里用简单移动平均实现
    （正式的 Wilder RSI 用指数平滑，差别很小，教学从简）。
    """
    delta = df["close"].diff()
    gain = delta.clip(lower=0.0)      # 只保留上涨部分
    loss = -delta.clip(upper=0.0)     # 只保留下跌部分（取正数）
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    # avg_loss 为 0 时 rs 为 inf，结果自然收敛到 100，无需特判
    return 100.0 - 100.0 / (1.0 + rs)


# ---------------------------------------------------------------- 因子 → 仓位

def factor_to_weights(factor: pd.Series, upper: float, lower: float | None = None) -> pd.Series:
    """
    把因子转成 0/1 仓位：因子值 > upper 就满仓，<= lower 就空仓，中间维持原状(NaN)。

    这是"规则书"的最简形态，用来演示"因子怎么变成交易信号"。
    注意：中间地带返回 NaN（= 维持现状不动），而不是强行给 0 或 1——避免来回震荡。
    """
    lower = upper if lower is None else lower
    w = pd.Series(float("nan"), index=factor.index)
    w[factor > upper] = 1.0
    w[factor <= lower] = 0.0
    return w


# ---------------------------------------------------------------- 现成策略（可直接回测）

def momentum_weights(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """
    动量策略：过去 lookback 天收益为正就满仓，否则空仓。

    与双均线同为"趋势跟踪"，但更简单——只有一个参数，适合当"我的第一个自制策略"。
    """
    roc = roc_factor(df, lookback)
    return factor_to_weights(roc, upper=0.0, lower=0.0)


def donchian_breakout_weights(df: pd.DataFrame, entry: int = 20, exit_: int = 10) -> pd.Series:
    """
    唐奇安通道突破（海龟交易法的核心）：价格创 entry 日新高就买入，跌破 exit 日新低就卖出。

    这是最经典的"趋势突破"策略，第 9 章机器人的换策略练习会用到它。
    注意 shift(1)：用"昨天"的通道判断"今天"——不能用今天收盘价去和"含今天的最高价"比，
    那是未来函数（今天还没收盘你怎么知道今天是不是新高）。
    """
    upper = df["close"].rolling(entry).max()
    lower = df["close"].rolling(exit_).min()
    w = pd.Series(float("nan"), index=df.index)
    w[df["close"] >= upper.shift(1)] = 1.0  # 突破昨日通道上沿 -> 满仓
    w[df["close"] <= lower.shift(1)] = 0.0  # 跌破昨日通道下沿 -> 空仓
    return w


def mean_reversion_weights(df: pd.DataFrame, lookback: int = 20, k: float = 2.0) -> pd.Series:
    """
    布林带均值回归：价格跌破"均线 - k*标准差"就买入（赌反弹），涨回均线就卖出。

    与趋势策略方向相反，赌的是"涨多了会跌、跌多了会涨"。
    均值回归策略的弱点：一旦遇到单边暴跌（跌破下轨后继续跌），会一路亏下去，
    所以实战必须配合止损（第 8 章）。
    """
    mid = df["close"].rolling(lookback).mean()
    std = df["close"].rolling(lookback).std()
    lower = mid - k * std
    w = pd.Series(float("nan"), index=df.index)
    w[df["close"] <= lower] = 1.0  # 超跌 -> 买入
    w[df["close"] >= mid] = 0.0    # 回到均线 -> 卖出
    return w


# 第 4 章的双均线也属于策略函数，但它已经住在 ch04_backtest/strategy.py 里，
# 回测和实盘都 import 它。这里不再重复定义，保持"唯一真源"。
