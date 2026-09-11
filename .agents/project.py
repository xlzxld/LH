# -*- coding: utf-8 -*-
"""本项目自己的门禁命令（tsc.py verify 会按顺序执行这里登记的 4 条命令）。

取值来源：AGENTS.md §2（check-config 校验同源）。
"""
__all__ = ["FMT_CHECK_CMD", "LINT_CMD", "TEST_CMD", "BUILD_CMD"]

FMT_CHECK_CMD = None
LINT_CMD = None
TEST_CMD = r".venv\Scripts\python.exe -m pytest code/tests/ -q"
BUILD_CMD = None
