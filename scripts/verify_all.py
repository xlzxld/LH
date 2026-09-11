# -*- coding: utf-8 -*-
"""
verify_all —— 一键通关校验（学习主线端到端自检，离线可跑）。

定位分工：
  * scripts/setup_check.py 检查"环境"（Python/依赖/网络/.env）
  * pytest               检查"单元"（引擎数学/配置解析）
  * 本脚本               检查"学习主线能不能端到端跑通"：数据 -> 单测 -> 回测 -> 产物

四步检查（全程离线，不访问任何网络接口）：
  1. 数据链路：固定种子样例数据生成 + OHLC 合法性校验
  2. 单元门禁：pytest 全量单测
  3. 端到端冒烟：--csv 离线跑通第 4 章双均线回测
  4. 产物检查：成交流水 CSV 已落盘且非空

用法（项目根目录，建议用项目虚拟环境的 python）：
    python scripts/verify_all.py
全部通过打印 ALL PASS 并退出 0；任何一步失败退出 1。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

SAMPLE_CSV = PROJECT_ROOT / "data" / "sample_prices.csv"
TRADES_CSV = PROJECT_ROOT / "data" / "output" / "dual_ma_sample_prices_trades.csv"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """跑子进程：强制 UTF-8 读输出，Windows GBK 控制台不会把中文输出搅成乱码。"""
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=PROJECT_ROOT)


# ---------------------------------------------------------------- 各步检查

def step_sample_data() -> tuple[bool, str]:
    """样例数据存在（不存在则现场生成）且 OHLC 形态合法、日期单调无重复。"""
    if not SAMPLE_CSV.exists():
        r = _run([PY, str(PROJECT_ROOT / "code" / "ch03_data" / "make_sample_data.py")])
        if r.returncode != 0:
            return False, f"样例数据生成失败: {(r.stderr or r.stdout).strip()[:200]}"

    import pandas as pd

    sys.path.insert(0, str(PROJECT_ROOT / "code"))
    from ch04_backtest.engine import validate_ohlcv  # noqa: E402

    df = pd.read_csv(SAMPLE_CSV, encoding="utf-8-sig", index_col=0, parse_dates=True)
    try:
        validate_ohlcv(df)  # 空表/缺列/非日期索引在这里抛错
    except Exception as exc:  # 校验失败就是失败，原样上报信息
        return False, str(exc)[:200]
    if not df.index.is_monotonic_increasing:
        return False, "日期非单调递增"
    envelope_ok = bool(
        (df["low"] <= df[["open", "close"]].min(axis=1)).all()
        and (df["high"] >= df[["open", "close"]].max(axis=1)).all()
    )
    detail = f"{len(df)} 行，{df.index[0].date()} ~ {df.index[-1].date()}"
    return envelope_ok, detail + ("（影线越界!）" if not envelope_ok else "")


def step_pytest() -> tuple[bool, str]:
    r = _run([PY, "-m", "pytest", "code/tests/", "-q"])
    lines = (r.stdout or r.stderr).strip().splitlines()
    return r.returncode == 0, (lines[-1] if lines else f"exit {r.returncode}")


def step_smoke_backtest() -> tuple[bool, str]:
    """第 4 章双均线脚本用 --csv 离线跑通，且输出里有绩效指标表。"""
    r = _run([PY, str(PROJECT_ROOT / "code" / "ch04_backtest" / "run_dual_ma.py"),
              "--csv", str(SAMPLE_CSV), "--no-plot"])
    if r.returncode != 0:
        return False, (r.stdout + r.stderr).strip()[:200]
    has_stats = "回测绩效指标" in (r.stdout or "")
    return has_stats, "第4章双均线离线跑通" if has_stats else "退出码 0 但未见绩效指标输出"


def step_trades_artifact() -> tuple[bool, str]:
    if not TRADES_CSV.exists():
        return False, f"缺少成交流水: {TRADES_CSV}"
    lines = TRADES_CSV.read_text(encoding="utf-8-sig").strip().splitlines()
    return len(lines) > 1, f"{len(lines) - 1} 笔成交已落盘"


# ---------------------------------------------------------------- 主流程

def main() -> int:
    steps = [
        ("1. 数据链路（固定种子样例 + OHLC 合法性）", step_sample_data),
        ("2. 单元门禁（pytest 全量）", step_pytest),
        ("3. 端到端冒烟（第4章双均线 --csv 离线回测）", step_smoke_backtest),
        ("4. 产物检查（成交流水落盘）", step_trades_artifact),
    ]
    results: list[tuple[str, bool]] = []
    for title, fn in steps:
        print(f"\n===== {title} =====")
        ok, note = fn()
        results.append((title, ok))
        print(f"[{'PASS' if ok else 'FAIL'}] {note}")

    print("\n" + "=" * 50)
    failed = [t for t, ok in results if not ok]
    if failed:
        for t in failed:
            print(f"[未通过] {t}")
        print(f"{len(failed)}/{len(results)} 项未通过——修复后再继续后续章节")
        return 1
    print("ALL PASS：数据 -> 单测 -> 回测 -> 产物 全链路可跑通，可以继续学习主线")
    return 0


if __name__ == "__main__":
    sys.exit(main())
