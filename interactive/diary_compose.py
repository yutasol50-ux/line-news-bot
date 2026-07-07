#!/usr/bin/env python3
"""下書き(原文+写真キャプション)をHaikuで忠実に清書し、title/tags/bodyを返す。

清書は「整えるだけ・盛らない」。失敗/パース不能時は原文をそのまま body に入れて
返す(日記を絶対に失わない。summarize.py と同じ思想)。
"""
import json
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path.home() / ".hermes" / ".env")

_MODEL = "claude-haiku-4-5"
_ENDPOINT = "https://api.anthropic.com/v1/messages"
_MAX_INPUT = 12000
_PROMPT = (
    "あなたはオーナー本人の日記を整えるアシスタントです。以下の下書きを、"
    "読みやすい日本語の日記本文に清書してください。\n"
    "【厳守】誤字・話し言葉・箇条書きを自然な文章に整えるだけ。"
    "書かれていない出来事や気持ちを足さない。事実を変えない。\n"
    "次のJSONだけを出力(前後に何も書かない):\n"
    '{{"title": "その日を一言で表す短い見出し", '
    '"tags": ["気分や出来事のタグを2〜3個"], '
    '"body": "清書した日記本文"}}\n\n'
    "--- 下書き ---\n{raw}"
)


def _fallback(raw: str, date: str) -> dict:
    return {"title": date, "tags": [], "body": raw.strip()}


def _extract_json(text: str):
    """本文からJSONオブジェクトを取り出してdict化。失敗時 None。"""
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def compose(raw: str, photo_captions=None, *, date: str, timeout: int = 30) -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    body = (raw or "").strip()
    if photo_captions:
        body += "\n\n[写真の内容]\n" + "\n".join(f"- {c}" for c in photo_captions if c)
    if not key or not body:
        return _fallback(raw, date)
    try:
        r = requests.post(
            _ENDPOINT,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": _MODEL, "max_tokens": 1024,
                  "messages": [{"role": "user",
                                "content": _PROMPT.format(raw=body[:_MAX_INPUT])}]},
            timeout=timeout,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", [])
                       if b.get("type") == "text").strip()
        obj = _extract_json(text)
        if not obj or "body" not in obj:
            return _fallback(raw, date)
        return {"title": (obj.get("title") or date).strip(),
                "tags": [str(t) for t in obj.get("tags", [])][:5],
                "body": str(obj["body"]).strip() or raw.strip()}
    except Exception as e:
        print(f"[ERROR] diary_compose: {e}")
        return _fallback(raw, date)
