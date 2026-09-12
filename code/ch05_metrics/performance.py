# -*- coding: utf-8 -*-
"""
绩效评估模块：给定一条净值曲线（equity curve），算出所有常用的回测指标。

新手最该盯的四个指标（重要程度排序）：
  1. max_drawdown   最大回撤 —— 你能忍受多大的亏损？这决定你敢不敢实盘
  2. sharpe         夏普比率 —— 每承受 1 份波动换来多少收益，>1 不错，>2 优秀
  3. cagr           年化收益率 —— 别被"3个月赚50%"迷惑，看年化
  4. n_trades       交易次数 —— 次数太少说明结果可能是运气，没有统计意义
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")  # 无窗口环境也能出图（服务器/定时任务必备）
import matplotlib.pyplot as plt  # noqa: E402

# 让图里的中文正常显示（Windows/移动端/macOS 各取所配字体）
plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei",              # Windows
    "PingFang SC", "Hiragino Sans GB",        # macOS
    "Noto Sans CJK SC", "WenQuanYi Zen Hei",  # Linux
]
plt.rcParams["axes.unicode_minus"] = False


def max_drawdown(equity: pd.Series) -> tuple[float, pd.Timestamp | None, pd.Timestamp | None]:
    """
    计算最大回撤。

    返回 (最大回撤比例, 峰值日期, 谷底日期)。回撤 = (净值 - 历史最高净值) / 历史最高净值。
    """
    if equity.empty:
        return 0.0, None, None
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    trough_date = drawdown.idxmin()
    peak_date = equity.loc[:trough_date].idxmax()
    return float(drawdown.loc[trough_date]), peak_date, trough_date


def compute_stats(
    equity: pd.Series,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.02,
) -> dict:
    """
    从净值曲线计算一整套绩效指标。

    :param equity: 净值序列（index 为日期，值为账户总市值）
    :param periods_per_year: 一年的采样期数，A股日线=252，币安日线=365，小时线A股=252*4
    :param risk_free_rate: 无风险利率（算夏普时分母里要减掉），默认 2%
    """
    equity = equity.dropna()
    if len(equity) < 2:
        return {}

    returns = equity.pct_change().dropna()
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0

    n_periods = len(equity) - 1
    years = n_periods / periods_per_year
    # 年化收益：几何平均（复利），而非简单线性放大
    cagr = (1.0 + total_return) ** (1.0 / years) - 1.0 if years > 0 else 0.0

    vol = returns.std(ddof=1) * np.sqrt(periods_per_year)  # 年化波动率
    excess = returns.mean() * periods_per_year - risk_free_rate
    sharpe = excess / vol if vol > 1e-12 else 0.0

    # 下行风险按标准口径: 对全部收益取 min(r, 0) 后求二阶矩 —— 曾只对"负收益
    # 子集"求 std, 正收益多的策略分母被人为缩小, 索提诺比率被系统性高估
    downside = returns.clip(upper=0.0)
    downside_vol = downside.std(ddof=1) * np.sqrt(periods_per_year) if len(downside) > 1 else 0.0
    sortino = (returns.mean() * periods_per_year - risk_free_rate) / downside_vol if downside_vol > 1e-12 else 0.0

    mdd, peak_d, trough_d = max_drawdown(equity)
    calmar = cagr / abs(mdd) if mdd < -1e-12 else 0.0

    return {
        "总收益率": total_return,
        "年化收益率(CAGR)": cagr,
        "年化波动率": vol,
        "夏普比率": sharpe,
        "索提诺比率": sortino,
        "最大回撤": mdd,
        "最大回撤区间": f"{peak_d} ~ {trough_d}" if peak_d is not None else "-",
        "卡玛比率": calmar,
        "最终权益": float(equity.iloc[-1]),
    }


def trade_stats(trades: list[dict]) -> dict:
    """从成交流水统计胜率、盈亏比、交易次数。"""
    if not trades:
        return {"交易次数": 0, "胜率": 0.0, "盈利交易平均收益": 0.0, "亏损交易平均收益": 0.0}

    # 把成交配对成"一笔完整的买卖"来算单笔盈亏：
    # 逐笔累加持仓，每次持仓从 >0 变回 0，就结算一笔 round-trip。
    closed: list[float] = []
    open_shares, open_cost = 0.0, 0.0
    for t in trades:
        if t["side"] == "BUY":
            new_shares = open_shares + t["shares"]
            open_cost += t["shares"] * t["price"] + t.get("fee", 0.0)
            open_shares = new_shares
        else:  # SELL
            sell_shares = min(t["shares"], open_shares)
            if sell_shares <= 0:
                continue
            # 卖出到手 = 市值 - 佣金 - 印花税(引擎对 A股个股会记 tax 字段,
            # 曾被漏算 → 个股口径下单笔收益与胜率略被高估)
            proceeds = (sell_shares * t["price"]
                        - t.get("fee", 0.0) - t.get("tax", 0.0))
            avg_cost = open_cost / open_shares if open_shares > 1e-12 else 0.0
            closed.append(proceeds / (avg_cost * sell_shares) - 1.0 if avg_cost > 0 else 0.0)
            open_shares -= sell_shares
            open_cost = avg_cost * open_shares
            if open_shares <= 1e-12:
                open_shares, open_cost = 0.0, 0.0

    wins = [r for r in closed if r > 0]
    losses = [r for r in closed if r <= 0]
    return {
        "交易次数": len(closed),
        "胜率": len(wins) / len(closed) if closed else 0.0,
        "盈利交易平均收益": float(np.mean(wins)) if wins else 0.0,
        "亏损交易平均收益": float(np.mean(losses)) if losses else 0.0,
    }


def print_stats(stats: dict) -> None:
    """把指标字典打印成对齐的表格。"""
    print("\n" + "=" * 46)
    print(f"{'回测绩效指标':^40}")
    print("=" * 46)
    for key, value in stats.items():
        if isinstance(value, float) and ("收益" in key or "回撤" in key or "波动" in key):
            print(f"  {key:<16}: {value:>10.2%}")
        elif isinstance(value, float):
            print(f"  {key:<16}: {value:>10.4f}")
        else:
            print(f"  {key:<16}: {value}")
    print("=" * 46)


def plot_equity(
    equity: pd.Series,
    benchmark: pd.Series | None = None,
    save_path: Path | str | None = None,
    title: str = "回测净值曲线",
) -> Path | None:
    """画出净值曲线（可选叠加基准），上方净值、下方回撤两栏。"""
    if equity.empty:
        return None
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 6.5), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    norm_equity = equity / equity.iloc[0]
    ax1.plot(norm_equity.index, norm_equity.values, label="策略净值", lw=1.6)
    if benchmark is not None and not benchmark.empty:
        bench = benchmark.reindex(norm_equity.index).ffill()
        ax1.plot(bench.index, bench.values / bench.iloc[0], label="基准（买入持有）", lw=1.2, alpha=0.8)
    ax1.axhline(1.0, color="gray", ls="--", lw=0.8)
    ax1.set_title(title)
    ax1.legend()
    ax1.grid(alpha=0.3)

    dd = norm_equity / norm_equity.cummax() - 1.0
    ax2.fill_between(dd.index, dd.values, 0, color="crimson", alpha=0.4)
    ax2.set_ylabel("回撤")
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    if save_path is not None:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=130)
        print(f"[图表] 已保存: {save_path}")
    plt.close(fig)
    return save_path
