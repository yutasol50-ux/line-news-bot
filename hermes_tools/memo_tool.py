#!/usr/bin/env python3
"""Hermes自作ツール: Notionにメモを追加。cli経由で既存 notion_memo を再利用。"""
import json

from hermes_tools.calendar_tool import _run  # subprocessヘルパを再利用(DRY)


def memo_add(content: str, tags: list = None, when: str = None) -> str:
    payload = {"content": content, "tags": tags, "when": when}
    return json.dumps(_run("memo_add", payload), ensure_ascii=False)


MEMO_ADD_SCHEMA = {
    "description": "ユーザーのNotionメモにメモを追加する。content必須。tagsは任意の文字列配列。",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "メモ本文"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "タグ(任意)"},
            "when": {"type": "string", "description": "日付 ISO8601(任意)"},
        },
        "required": ["content"],
    },
}

try:
    from tools import registry

    registry.register(
        name="memo_add",
        toolset="line_secretary",
        schema=MEMO_ADD_SCHEMA,
        handler=lambda args, **kw: memo_add(
            args.get("content", ""), args.get("tags"), args.get("when"),
        ),
        emoji="📝",
    )
except Exception:
    pass
