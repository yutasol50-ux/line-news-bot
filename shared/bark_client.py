#!/usr/bin/env python3
"""Bark 通知クライアント。通知ごとにアイコン/サウンド/グループを変えられる。

Bark は iOS の「どの通知か一目で分かる」用途に強い(通知ごとにカスタムアイコン, iOS15+)。
BARK_KEY 未設定なら何もしない(グレースフル)。
"""
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BARK_KEY = os.environ.get("BARK_KEY", "")
BARK_BASE = os.environ.get("BARK_BASE", "https://api.day.app")


def notify(title: str, body: str, *, icon: str = "", group: str = "",
           sound: str = "", url: str = "") -> bool:
    """Bark に通知を送る。未設定なら False を返して何もしない。

    icon: 通知に表示する画像URL(通知ごとに変えられる)。group: 通知のまとめ名。
    sound: 着信音名。url: 通知タップ時に開くURL。
    """
    if not BARK_KEY:
        return False
    payload = {"title": title, "body": body}
    if icon:
        payload["icon"] = icon
    if group:
        payload["group"] = group
    if sound:
        payload["sound"] = sound
    if url:
        payload["url"] = url
    try:
        resp = requests.post(f"{BARK_BASE}/{BARK_KEY}", json=payload, timeout=15)
        if resp.status_code == 200:
            return True
        print(f"[ERROR] Bark通知失敗: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Bark通知例外: {e}")
    return False
