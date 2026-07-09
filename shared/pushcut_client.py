#!/usr/bin/env python3
"""Pushcut 通知クライアント。秘密キー越しに事前定義の notification をトリガーする。

Pushcut 側(アプリ)で通知(例「承認待ち」)に「承認/却下」の Web リクエストボタンを
設定しておき、ここからは名前で叩くだけ。PUSHCUT_SECRET 未設定なら何もしない(グレースフル)。
"""
import os
import urllib.parse
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

PUSHCUT_SECRET = os.environ.get("PUSHCUT_SECRET", "")
PUSHCUT_NOTIFICATION = os.environ.get("PUSHCUT_NOTIFICATION", "承認待ち")


def notify(title: str = "", text: str = "") -> bool:
    """Pushcut の notification をトリガー。未設定なら False を返して何もしない。"""
    if not PUSHCUT_SECRET:
        return False
    name = urllib.parse.quote(PUSHCUT_NOTIFICATION, safe="")
    url = f"https://api.pushcut.io/{PUSHCUT_SECRET}/notifications/{name}"
    body = {}
    if title:
        body["title"] = title
    if text:
        body["text"] = text
    try:
        resp = requests.post(url, json=body, timeout=15)
        if resp.status_code == 200:
            return True
        print(f"[ERROR] Pushcut通知失敗: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Pushcut通知例外: {e}")
    return False
