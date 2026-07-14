#!/usr/bin/env python3
"""Claude Code 専用 Telegram bot への通知クライアント。

承認待ち等を Telegram(@watanabe_claudecode_bot) に push する。
CLAUDE_TG_BOT_TOKEN / CLAUDE_TG_CHAT_ID 未設定なら何もしない(グレースフル)。
pushcut_client.py と同じ「未設定なら no-op」方針。
"""
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CLAUDE_TG_BOT_TOKEN = os.environ.get("CLAUDE_TG_BOT_TOKEN", "")
CLAUDE_TG_CHAT_ID = os.environ.get("CLAUDE_TG_CHAT_ID", "")


def notify(text: str, *, token: str = None, chat_id: str = None,
           post=requests.post) -> bool:
    """テキストを Claude Code 用 Telegram bot から push。
    未設定(token/chat無)なら何もせず False。成功で True。"""
    token = token if token is not None else CLAUDE_TG_BOT_TOKEN
    chat_id = chat_id if chat_id is not None else CLAUDE_TG_CHAT_ID
    if not token or not chat_id:
        return False
    try:
        resp = post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        if resp.status_code == 200:
            return True
        print(f"[ERROR] Telegram通知失敗: {resp.status_code}")
    except Exception as e:
        print(f"[ERROR] Telegram通知例外: {type(e).__name__}")
    return False
