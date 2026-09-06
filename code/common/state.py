# -*- coding: utf-8 -*-
"""
状态持久化模块：机器人"记忆"的唯一读写入口。

为什么需要它（Eng 评审 M12/1c.6 的结论）：
  * 机器人崩溃/断电时，如果状态文件只写了一半，下次启动读到残缺 JSON 会引发
    更严重的连锁错误 —— 所以写入必须是"原子"的（先写临时文件再改名）。
  * 读取时文件可能损坏/不存在 —— 必须容错降级，而不是让机器人起不来。
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def load_state(path: Path, default: dict | None = None) -> dict:
    """容错读取 JSON 状态文件：不存在/损坏都返回 default，绝不抛异常打断主流程。"""
    if default is None:
        default = {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(default)
    except Exception as exc:  # 损坏的 JSON / 编码问题
        print(f"[警告] 状态文件 {path} 读取失败（{exc}），按空状态继续")
        return dict(default)


def save_state(path: Path, state: dict) -> None:
    """原子写入：先写 .tmp 再 os.replace，任何时刻磁盘上都只有完整文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # 原子操作：改名要么成功要么失败，不会写一半
