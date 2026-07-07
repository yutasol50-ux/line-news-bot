#!/usr/bin/env python3
"""LINE Messaging APIからメディア本体(画像/ファイル)を取得する薄い層。

人間→ボットのメディアは message.id で `api-data.line.me` から本体を落とせる。
認証は push/reply と同じ LINE_ACCESS_TOKEN。取得失敗は呼び出し側(media_intake)が
握ってユーザーへ定型文を返すため、ここでは素直に例外を投げる。
"""
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_ENDPOINT = "https://api-data.line.me/v2/bot/message/{mid}/content"


def fetch_content(message_id, *, token=None, timeout=30):
    """(bytes, content_type) を返す。content_type は小文字・パラメータ除去済み。"""
    token = token or os.environ.get("LINE_ACCESS_TOKEN", "")
    r = requests.get(
        _ENDPOINT.format(mid=message_id),
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    r.raise_for_status()
    ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    return r.content, ctype
