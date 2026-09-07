# -*- coding: utf-8 -*-
"""
统一配置加载模块（全项目唯一读取配置的地方）

设计原则（对新手友好）：
1. 所有配置集中放在项目根目录的 ``.env`` 文件里（先复制 ``.env.example`` 为 ``.env``）。
2. 秘密信息（API Key 等）只存在于 .env，绝不写死在代码里，也不上传到 git。
3. 代码里永远通过 ``cfg.get(...)`` / ``cfg.get_float(...)`` 读取，带默认值，
   这样零配置也能先跑通（例如不配推送渠道时自动退化为打印到控制台）。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# code/common/config.py -> 向上两级 = 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
STATE_DIR = DATA_DIR / "state"
OUTPUT_DIR = DATA_DIR / "output"

_env_loaded = False


def load_env() -> None:
    """加载 .env 文件（幂等，可重复调用）。"""
    global _env_loaded
    if not _env_loaded:
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        _env_loaded = True


def ensure_dirs() -> None:
    """确保 data/、data/state/、data/output/ 目录存在。"""
    for d in (DATA_DIR, STATE_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def get(key: str, default: str | None = None) -> str | None:
    """读取字符串配置。"""
    load_env()
    val = os.environ.get(key, default)
    if val is not None:
        val = val.strip()
        if val == "":
            val = default
    return val


def get_bool(key: str, default: bool = False) -> bool:
    val = get(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "y", "on")


def get_int(key: str, default: int) -> int:
    val = get(key)
    if val is not None and "." in val:  # "60.5" 这类笔误会被截断成 60，必须吭声
        print(f"[警告] 配置 {key}={val!r} 不是整数，已截断为 {int(float(val))}；请检查 .env")
    try:
        return int(float(val)) if val is not None else default
    except (TypeError, ValueError):
        return default


def get_float(key: str, default: float) -> float:
    val = get(key)
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def get_list(key: str, default: list[str] | None = None) -> list[str]:
    """读取逗号分隔的列表配置，如 ``WATCHLIST=etf:510300,stock:600519``。"""
    val = get(key)
    if not val:
        return default or []
    return [item.strip() for item in val.split(",") if item.strip()]


# ============ 项目里常用的配置项快捷方式 ============

def notify_channel() -> str:
    """微信推送渠道：serverchan / pushplus / wecom / off（off=只打印）。"""
    return (get("NOTIFY_CHANNEL", "off") or "off").lower()


def exchange_id() -> str:
    """现货交易所 id（ccxt 支持 binance / okx / bybit ...）。"""
    return (get("EXCHANGE_ID", "binance") or "binance").lower()


def use_testnet() -> bool:
    """币安是否使用模拟盘（testnet）。强烈建议新手先保持 true。"""
    return get_bool("BINANCE_TESTNET", True)
