# -*- coding: utf-8 -*-
"""
数据获取模块：量化的一切从数据开始。

本模块提供三类数据源（都不需要付费）：
  1. A股/ETF 日线   -> 东方财富公开 K 线接口（requests 直连，无需注册）
  2. A股/ETF 实时快照 -> 东方财富实时行情接口（用于盘中监测）
  3. 加密货币 K线    -> ccxt 库（支持 binance/okx/bybit 等上百家交易所统一接口）

> 为什么不直接用 akshare？
> akshare 是最流行的开源数据接口库（教程里会介绍），但它底层依赖较多、更新频繁，
> 新手环境容易装失败。东方财富接口只依赖 requests，稳如老狗，所以本项目把它
> 作为默认数据源；akshare 的用法在第 3 章文档里完整讲解，两者返回格式一致。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

# 让本文件无论从哪里运行都能 import 到 code/ 下的其他模块
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common.config as cfg  # noqa: E402

TIMEOUT = 15
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 quant-tutorial/1.0"}


def _get_with_retry(url: str, params: dict, tries: int = 3, backoff: float = 1.5) -> dict:
    """
    带重试的 GET：免费接口偶发断连/限流是常态，工程上永远要有重试。
    每次失败等待时间翻倍（1.5s -> 3s -> 6s），三次都失败才抛异常。
    4xx 客户端错误（参数/权限问题，429 限流除外）重试也不会好，立即失败。
    """
    import time as _time

    last_exc: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            resp = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status is not None and 400 <= status < 500 and status != 429:
                raise RuntimeError(f"请求 {url} 被拒绝（HTTP {status}），请检查参数/权限"
                                   "（客户端错误不重试）") from exc
            last_exc = exc
        except Exception as exc:
            last_exc = exc
        if attempt < tries:
            wait = backoff * (2 ** (attempt - 1))
            print(f"[重试] 请求失败（第{attempt}次）：{last_exc}，{wait:.0f}s 后重试…")
            _time.sleep(wait)
    raise RuntimeError(f"请求 {url} 连续 {tries} 次失败") from last_exc


# ================================================================ A股 / ETF

def _eastmoney_secid(code: str) -> str:
    """
    把 6 位代码转成东方财富的 secid：沪市前缀 1，深市前缀 0。
    规则（覆盖常见品种）：5/6/9 开头 = 上海（51x ETF、6xx 股票），
    0/1/3 开头 = 深圳（15x ETF、0xx/3xx 股票）。
    北交所（4/8 开头）不在此数据源覆盖范围，显式拒绝而非误判成深市。
    """
    code = code.strip()
    if not (code.isdigit() and len(code) == 6):
        raise ValueError(f"非法代码: {code!r}，应为 6 位数字，如 510300 / 000001")
    if code[0] in "48":
        raise ValueError(f"暂不支持代码 {code!r}（北交所/三板，本项目数据源仅覆盖沪深两市）")
    market = "1" if code[0] in "569" else "0"
    return f"{market}.{code}"


def fetch_eastmoney_daily(
    code: str,
    start: str = "20180101",
    end: str = "20500101",
    adjust: str = "qfq",
) -> pd.DataFrame:
    """
    拉取 A股/ETF 日线（东方财富公开接口）。

    :param code: 6 位代码，如 "510300"（沪深300ETF）、"000001"（平安银行）
    :param start/end: "YYYYMMDD"
    :param adjust: "qfq"前复权 / "hfq"后复权 / ""不复权。
        回测默认用前复权！否则历史分红除权日会出现假跳空，信号全是错的。
    :return: DataFrame，index=日期，列 open/close/high/low/volume/amount
    """
    fqt = {"qfq": 1, "hfq": 2}.get(adjust, 0)
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": _eastmoney_secid(code),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": 101,  # 101=日线
        "fqt": fqt,
        "beg": start,
        "end": end,
        "lmt": 100000,
    }
    data = (_get_with_retry(url, params) or {}).get("data") or {}
    klines = data.get("klines") or []
    if not klines:
        raise RuntimeError(f"未获取到 {code} 的K线数据，请检查代码是否正确（接口返回: {data.get('name')}）")

    rows = [line.split(",") for line in klines]
    df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume", "amount"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").astype(float)
    df.index.name = "date"
    df.attrs["symbol"] = code
    return df


def fetch_realtime_quotes(codes: list[str]) -> pd.DataFrame:
    """
    实时行情快照（盘中监测用）。收盘后调用返回的是当天收盘数据。

    :return: DataFrame(index=代码, 列: 名称/最新价/涨跌幅/今开/最高/最低)
    """
    if not codes:
        return pd.DataFrame()
    secids = ",".join(_eastmoney_secid(c) for c in codes)
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "fltt": 2,  # 让价格直接以小数返回（否则是放大 100 倍的整数）
        "invt": 2,
        "fields": "f2,f3,f12,f14,f15,f16,f17,f18",  # 最新价,涨跌幅,代码,名称,最高,最低,今开,昨收
        "secids": secids,
    }
    resp = _get_with_retry(url, params)
    diff = (resp.get("data") or {}).get("diff") or []
    if not diff:
        raise RuntimeError(f"实时行情返回为空: {codes}")
    rows = {}
    for item in diff:
        rows[str(item["f12"])] = {
            "名称": item.get("f14"),
            "最新价": item.get("f2"),
            "涨跌幅%": item.get("f3"),
            "今开": item.get("f17"),
            "昨收": item.get("f18"),
            "最高": item.get("f15"),
            "最低": item.get("f16"),
        }
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "代码"
    return df


def fetch_astock_daily_akshare(code: str, start: str, end: str, adjust: str = "qfq") -> pd.DataFrame:
    """
    akshare 版本的数据获取（可选，需 pip install akshare）。
    教学价值：让你认识社区最流行的数据接口，用法几乎一样。
    """
    try:
        import akshare as ak  # 延迟导入：没装也不影响其他功能
    except ImportError as exc:
        raise ImportError("请先安装 akshare: pip install akshare") from exc

    raw = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust=adjust)
    df = raw.rename(
        columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"}
    )
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")[["open", "close", "high", "low", "volume"]].astype(float)


# ================================================================ 加密货币

def fetch_crypto_ohlcv(
    symbol: str = "BTC/USDT",
    timeframe: str = "1d",
    limit: int = 1000,
    exchange=None,
    exchange_id: str | None = None,
) -> pd.DataFrame:
    """
    拉取加密货币K线（公共数据，不需要 API Key）。

    :param symbol: ccxt 统一格式 "BTC/USDT"、"ETH/USDT"
    :param timeframe: "1m"/"5m"/"1h"/"4h"/"1d" ...
    :param limit: 最多拉多少根（一次最多 1000）
    :param exchange: 传入已有的 ccxt 实例（实盘机器人复用连接），不传则新建
    """
    if exchange is None:
        from common.exchange import make_exchange
        exchange = make_exchange(exchange_id, with_keys=False, testnet=False)
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    if not raw:
        raise RuntimeError(f"{exchange.id} 未返回 {symbol} 数据，检查网络（国内直连可能需要代理）")
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("ts").astype(float)
    df.index.name = "date"
    df.attrs["symbol"] = symbol
    return df


# ================================================================ 本地存取

def save_csv(df: pd.DataFrame, name: str) -> Path:
    """保存到 data/ 目录。utf-8-sig 编码保证用 Excel 打开中文不乱码。"""
    cfg.ensure_dirs()
    path = cfg.DATA_DIR / f"{name}.csv"
    df.to_csv(path, encoding="utf-8-sig")
    print(f"[数据] 已保存 {path}（{len(df)} 行）")
    return path


def load_csv(name: str) -> pd.DataFrame:
    """从 data/ 目录读取，index 解析为日期。"""
    path = cfg.DATA_DIR / f"{name}.csv"
    df = pd.read_csv(path, encoding="utf-8-sig", index_col=0, parse_dates=True)
    return df


def fetch_daily_with_cache(code: str, start: str = "20180101",
                           end: str = "20500101") -> pd.DataFrame:
    """
    带本地缓存的日线获取：网络优先，失败回退到最近一次下载的 CSV。
    免费接口偶发限流（东财对高频请求会临时断连），缓存让你离线也能继续工作。
    教训：免费数据源 = 永远准备 Plan B。
    回退时打上 from_cache 标记——推送消息里要告诉用户"数据是几号的"。
    """
    try:
        df = fetch_eastmoney_daily(code, start=start, end=end)
        save_csv(df, f"astock_{code}")
        return df
    except Exception as exc:
        cache = cfg.DATA_DIR / f"astock_{code}.csv"
        if cache.exists():
            print(f"[警告] 网络获取失败（{exc}），使用本地缓存 {cache}")
            df = load_csv(f"astock_{code}")
            df.attrs["from_cache"] = True
            return df
        raise
