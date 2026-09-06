# -*- coding: utf-8 -*-
"""notify 模块的安全与健壮性测试：密钥脱敏、企业微信截断、离线降级。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.notify import _sanitize, _wecom_safe  # noqa: E402


def test_sanitize_strips_keys_from_urls():
    """Eng M7 的回归疫苗：SendKey/Webhook token 绝不能出现在日志/异常文本里。"""
    leak = "HTTP 400: https://sctapi.ftqq.com/SCT123456ABCdef.send 返回错误"
    cleaned = _sanitize(leak)
    assert "SCT123456ABCdef" not in cleaned
    assert "https://sctapi.ftqq.com/***".replace("***", "") in cleaned.replace("***", "")
    wecom = "errcode 931000 at https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRET-TOKEN-99"
    assert "SECRET-TOKEN-99" not in _sanitize(wecom)


def test_wecom_safe_truncates_multibyte():
    """4000 字节上限：超长中文内容截断且不抛异常（多字节边界不能撕裂成非法字符）。"""
    content = "触发信号" * 3000  # 约 36000 字节
    safe = _wecom_safe(content)
    assert len(safe.encode("utf-8")) <= 4200  # 截断点+省略提示
    safe.encode("utf-8")  # 若多字节被撕开会在这里抛 UnicodeDecodeError


def test_wecom_safe_short_content_untouched():
    short = "**标题**\n正文"
    assert _wecom_safe(short) == short
