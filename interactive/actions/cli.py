#!/usr/bin/env python3
"""Hermesツールから subprocess で呼ぶCLI入口。

.env を読み込み、既存の action 関数へ振り分ける。認証情報は line-news-bot 側に留める。
使い方: python -m interactive.actions.cli <cmd> '<json>'
  cmd: calendar_add | memo_add | calendar_read
"""
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env")


def _calendar_add(**kwargs) -> str:
    from interactive.actions import calendar_add
    return calendar_add.add(
        title=kwargs["title"], start_iso=kwargs["start"],
        end_iso=kwargs.get("end"), all_day=kwargs.get("all_day", False),
    )


def _memo_add(**kwargs) -> str:
    from interactive.actions import notion_memo
    return notion_memo.add(
        content=kwargs["content"], tags=kwargs.get("tags"),
        when_iso=kwargs.get("when"),
    )


def _calendar_read() -> str:
    from briefing import calendar_events
    return calendar_events.get_calendar_block()


def main(argv: list) -> dict:
    if len(argv) < 2:
        return {"ok": False, "error": "no command"}
    cmd = argv[1]
    payload = {}
    if len(argv) >= 3 and argv[2].strip():
        payload = json.loads(argv[2])
    if cmd == "calendar_add":
        return {"ok": True, "link": _calendar_add(**payload)}
    if cmd == "memo_add":
        return {"ok": True, "url": _memo_add(**payload)}
    if cmd == "calendar_read":
        return {"ok": True, "block": _calendar_read()}
    return {"ok": False, "error": f"unknown command: {cmd}"}


if __name__ == "__main__":
    try:
        print(json.dumps(main(sys.argv), ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)
