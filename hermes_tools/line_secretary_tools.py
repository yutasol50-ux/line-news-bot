#!/usr/bin/env python3
"""Hermes登録アダプタ: line_secretary toolset(予定/メモ)をHermesに登録する。

このファイルは ~/.hermes/hermes-agent/tools/ へ flat symlink して使う(Hermes本体でのみ有効)。
発見器 discover_builtin_tools は tools/ 直下の *.py を非再帰で走査し、静的検査
_module_registers_tools が「モジュール直下の registry.register(...) 呼び出し」を要求する。
そのため registry.register は try/if で包まず、必ずモジュール直下で呼ぶこと。
ロジック本体とスキーマは line-news-bot 側の hermes_tools パッケージに置き、ここは薄い配線のみ。
"""
import os
import sys

# line-news-bot をパスに載せ、ロジックとスキーマを取り込む
sys.path.insert(0, os.path.expanduser("~/line/line-news-bot"))

from hermes_tools.calendar_tool import (
    calendar_add, calendar_read, reminder_add,
    CALENDAR_ADD_SCHEMA, CALENDAR_READ_SCHEMA, REMINDER_ADD_SCHEMA,
)
from hermes_tools.memo_tool import memo_add, MEMO_ADD_SCHEMA
from tools.registry import registry

registry.register(
    name="calendar_add",
    toolset="line_secretary",
    schema=CALENDAR_ADD_SCHEMA,
    handler=lambda args, **kw: calendar_add(
        args.get("title", ""), args.get("start", ""),
        args.get("end"), args.get("all_day", False),
    ),
    emoji="📅",
)
registry.register(
    name="calendar_read",
    toolset="line_secretary",
    schema=CALENDAR_READ_SCHEMA,
    handler=lambda args, **kw: calendar_read(),
    emoji="📅",
)
registry.register(
    name="reminder_add",
    toolset="line_secretary",
    schema=REMINDER_ADD_SCHEMA,
    handler=lambda args, **kw: reminder_add(
        args.get("text", ""), args.get("at", ""),
    ),
    emoji="⏰",
)
registry.register(
    name="memo_add",
    toolset="line_secretary",
    schema=MEMO_ADD_SCHEMA,
    handler=lambda args, **kw: memo_add(
        args.get("content", ""), args.get("tags"), args.get("when"),
    ),
    emoji="📝",
)
