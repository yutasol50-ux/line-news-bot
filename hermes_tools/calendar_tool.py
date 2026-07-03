#!/usr/bin/env python3
"""Hermes自作ツール: Googleカレンダーの予定 登録/照会。

line-news-bot の venv/env へ subprocess し、既存 action を再利用する
(認証情報を Hermes 側に持ち込まないため)。
"""
import os
import json
import subprocess

_LNB = os.path.expanduser("~/line/line-news-bot")
_PY = os.path.join(_LNB, "venv/bin/python")


def _run(cmd: str, payload: dict) -> dict:
    try:
        proc = subprocess.run(
            [_PY, "-m", "interactive.actions.cli", cmd, json.dumps(payload, ensure_ascii=False)],
            cwd=_LNB, capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            return {"ok": False, "error": (proc.stderr or proc.stdout).strip()[:300]}
        last = proc.stdout.strip().splitlines()[-1]
        return json.loads(last)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def calendar_add(title: str, start: str, end: str = None, all_day: bool = False) -> str:
    payload = {"title": title, "start": start, "end": end, "all_day": all_day}
    return json.dumps(_run("calendar_add", payload), ensure_ascii=False)


def calendar_read() -> str:
    return json.dumps(_run("calendar_read", {}), ensure_ascii=False)


CALENDAR_ADD_SCHEMA = {
    "description": (
        "ユーザーのGoogleカレンダーに予定を登録する。予定名(title)は発話をそのまま写さず"
        "簡潔にまとめる。start/endはISO8601(例 2026-07-04T15:00:00+09:00)。"
        "終日なら all_day=true。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "簡潔な予定名"},
            "start": {"type": "string", "description": "開始 ISO8601(+09:00)"},
            "end": {"type": "string", "description": "終了 ISO8601(任意)"},
            "all_day": {"type": "boolean", "description": "終日ならtrue"},
        },
        "required": ["title", "start"],
    },
}

CALENDAR_READ_SCHEMA = {
    "description": "ユーザーの直近のカレンダー予定を読み取り、一覧テキストを返す。「予定あったっけ」等の照会に使う。",
    "parameters": {"type": "object", "properties": {}},
}

# Hermesへの登録は hermes_tools/line_secretary_tools.py(発見器に拾わせるアダプタ)で行う。
# このファイルはロジックとスキーマのみを提供し、単体で import できる状態に保つ。
