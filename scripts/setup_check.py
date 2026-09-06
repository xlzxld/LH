# -*- coding: utf-8 -*-
"""
环境自检脚本：新电脑上跑一遍，哪里有问题一眼看出来。

用法：python scripts/setup_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# ✅❌ 等 emoji 在 Windows GBK 控制台会直接 UnicodeEncodeError——先切 UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "code"))

OK, BAD, WARN = "✅", "❌", "⚠️ "


def check(title: str, fn, warn_only: bool = False) -> None:
    try:
        detail = fn()
        print(f"{OK} {title}" + (f" —— {detail}" if detail else ""))
    except Exception as exc:
        mark = WARN if warn_only else BAD
        print(f"{mark} {title} —— {exc}")


def py_version() -> str:
    v = sys.version_info
    if v < (3, 10):
        raise RuntimeError(f"Python {v.major}.{v.minor} 太旧，需要 3.10+")
    return f"Python {v.major}.{v.minor}.{v.micro}"


def has_module(name: str, hint: str):
    def _f():
        mod = __import__(name)
        return getattr(mod, "__version__", None) or "已安装"
    _f.__doc__ = hint
    return _f


def network_any(*urls):
    """多个端点任一可达即通过（免费接口偶发限流，给备用域名）。"""
    def _f():
        import urllib.request
        last_err = None
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 quant-tutorial/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        return "可达"
            except Exception as exc:
                last_err = exc
        raise RuntimeError(f"不可达（免费接口偶发限流，稍后再试）: {last_err}")
    return _f


def main() -> None:
    print("=" * 60)
    print("量化教程项目 · 环境自检")
    print("=" * 60)

    check("Python 版本", py_version)

    for mod, hint in [
        ("pandas", "pip install pandas"),
        ("numpy", "pip install numpy"),
        ("matplotlib", "pip install matplotlib"),
        ("requests", "pip install requests"),
        ("dotenv", "pip install python-dotenv"),
        ("ccxt", "pip install ccxt"),
    ]:
        check(f"依赖库 {mod}", has_module(mod, hint), warn_only=(mod == "ccxt"))

    check("依赖库 akshare（可选）", has_module("akshare", "pip install akshare"), warn_only=True)

    check("A股数据（东方财富）", network_any(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.510300&fields1=f1&fields2=f51,f53&klt=101&fqt=1&lmt=5",
        "https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f12&secids=1.510300"))
    check("币安测试网（需代理则显示失败）", network_any("https://testnet.binance.vision/api/v3/ping"), warn_only=True)
    check("PyPI", network_any("https://pypi.org/simple/"), warn_only=True)

    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        print(f"{OK} .env 配置文件存在")
        sys.path.insert(0, str(PROJECT_ROOT / "code"))
        from common import config
        config.load_env()
        channel = config.notify_channel()
        print(f"   推送渠道 NOTIFY_CHANNEL = {channel}" +
              ("" if channel != "off" else "（第 10 章开通后改为 serverchan/pushplus/wecom）"))
        print(f"   币安测试网 BINANCE_TESTNET = {config.use_testnet()}")
        key = config.get("BINANCE_API_KEY")
        print(f"   币安 API Key = {'已配置' if key else '未配置（第 9 章再配）'}")
    else:
        print(f"{WARN} 未找到 .env —— 请先复制 .env.example 为 .env")

    # pytest 检查：只认 venv 里的真实路径，别再"永远绿"
    venv_pytest = PROJECT_ROOT / ".venv" / "Scripts" / "pytest.exe"
    if not venv_pytest.exists():
        venv_pytest = PROJECT_ROOT / ".venv" / "bin" / "pytest"
    if venv_pytest.exists():
        print(f"{OK} pytest 可用：{venv_pytest}")
        print(f"      验证回测引擎请运行: {venv_pytest} code/tests/ -v")
    else:
        print(f"{WARN} 未在 .venv 里找到 pytest —— 运行: .venv\\Scripts\\python.exe -m pip install pytest")

    print("=" * 60)
    print("自检完成。全部 ❌ 修复后再继续课程；⚠️ 项可视章节需要处理。")


if __name__ == "__main__":
    main()
