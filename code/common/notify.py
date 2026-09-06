# -*- coding: utf-8 -*-
"""
微信推送模块：让 Python 机器人把消息发到你手机微信上。

支持三个免费渠道（在 .env 里用 NOTIFY_CHANNEL 选择其一）：
  1. serverchan —— Server酱·Turbo 版（https://sct.ftqq.com）
       微信扫码登录 -> 复制 SendKey -> 填进 .env 的 SERVERCHAN_SENDKEY
       免费额度：每天约 5 条（多的要付费），适合"信号不频繁"的场景
  2. pushplus  —— PushPlus（https://www.pushplus.plus）
       微信扫码登录 -> 复制 token -> 填进 .env 的 PUSHPLUS_TOKEN
       免费额度比 Server酱宽松，个人学习够用
  3. wecom     —— 企业微信群机器人 Webhook（免费、无条数限制、最稳定）
       微信里建一个企业微信群（个人也能建）-> 群设置 -> 添加群机器人
       -> 复制 Webhook 地址 -> 填进 .env 的 WECOM_WEBHOOK

使用方法（两行代码）：
    from common.notify import send_text
    send_text("双均线金叉", "510300 触发买入信号，请手动下单")
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request

from common import config

# Windows 控制台默认 GBK：emoji（🔔💓）会让 print 直接 UnicodeEncodeError。
# 统一切到 UTF-8 输出，遇到编码不了的字符用占位替代，绝不崩主流程。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


class NotifyError(RuntimeError):
    pass


def _sanitize(text: str) -> str:
    """脱敏：报错信息里的 URL 可能带着 SendKey/Webhook token，落日志前必须抹掉。"""
    return re.sub(r"(https?://[^\s?/]+/)[^\s\"']+", r"\1***", str(text))


# ---------------------------------------------------------------- 工具函数

def _http_post(url: str, payload: dict, timeout: float = 15.0) -> dict:
    """极简 POST（用标准库，避免额外依赖）。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _wecom_safe(content: str, limit: int = 4000) -> str:
    """企业微信 markdown 消息上限约 4096 字节，超长时截断。"""
    encoded = content.encode("utf-8")
    if len(encoded) <= limit:
        return content
    return encoded[:limit].decode("utf-8", errors="ignore") + "\n\n…(消息过长已截断)"


# ---------------------------------------------------------------- 三个渠道

def _send_serverchan(title: str, content: str) -> str:
    key = config.get("SERVERCHAN_SENDKEY")
    if not key:
        raise NotifyError("未配置 SERVERCHAN_SENDKEY（见 .env.example）")
    # Server酱支持 form 或 json，这里用 UTF-8 JSON 避免 Windows 编码坑
    resp = _http_post(
        f"https://sctapi.ftqq.com/{key}.send",
        {"title": title[:32], "desp": content},  # 标题最长 32 字
    )
    if resp.get("code") != 0:
        raise NotifyError(f"Server酱返回错误: {resp}")
    return "Server酱推送成功"


def _send_pushplus(title: str, content: str) -> str:
    token = config.get("PUSHPLUS_TOKEN")
    if not token:
        raise NotifyError("未配置 PUSHPLUS_TOKEN（见 .env.example）")
    resp = _http_post(
        "https://www.pushplus.plus/send",
        {"token": token, "title": title[:100], "content": content, "template": "markdown"},
    )
    if resp.get("code") != 200:
        raise NotifyError(f"PushPlus返回错误: {resp}")
    return "PushPlus推送成功"


def _send_wecom(title: str, content: str) -> str:
    webhook = config.get("WECOM_WEBHOOK")
    if not webhook:
        raise NotifyError("未配置 WECOM_WEBHOOK（见 .env.example）")
    body = {"msgtype": "markdown", "markdown": {"content": _wecom_safe(f"**{title}**\n{content}")}}
    resp = _http_post(webhook, body)
    if resp.get("errcode") != 0:
        raise NotifyError(f"企业微信返回错误: {resp}")
    return "企业微信推送成功"


_CHANNELS = {
    "serverchan": _send_serverchan,
    "pushplus": _send_pushplus,
    "wecom": _send_wecom,
}


# ---------------------------------------------------------------- 对外接口

def send_text(title: str, content: str, *, raise_on_fail: bool = False) -> bool:
    """
    发送一条微信消息（按 .env 里 NOTIFY_CHANNEL 选择渠道）。

    :param title: 消息标题（微信通知栏里看到的那行字）
    :param content: 正文，支持 Markdown
    :param raise_on_fail: True 时发送失败抛异常；默认只打印警告，不打断主流程
    :return: 是否成功
    """
    channel = config.notify_channel()
    if channel == "off":
        print(f"\n[微信推送已关闭 NOTIFY_CHANNEL=off] {title}\n{content}\n")
        return True

    sender = _CHANNELS.get(channel)
    if sender is None:
        print(f"[警告] 未知推送渠道 {channel!r}，可选: {list(_CHANNELS)} / off")
        return False

    try:
        msg = sender(title, content)
        print(f"[推送] {msg}: {title}")
        return True
    except Exception as exc:  # 网络/配置问题都不应让主程序崩溃
        print(f"[推送失败] {channel}: {_sanitize(exc)}")  # URL 里的密钥已脱敏
        if raise_on_fail:
            raise
        return False
