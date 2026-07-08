#!/usr/bin/env python3
"""LINE送受信クライアント。push(自発送信) と reply(応答) を提供。"""
import os
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

LINE_ACCESS_TOKEN = os.environ["LINE_ACCESS_TOKEN"]
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")
_HEADERS = {
    "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}


def push(text: str) -> bool:
    chunks = [text[i:i + 4900] for i in range(0, len(text), 4900)] or [""]
    success = True
    for chunk in chunks:
        try:
            resp = requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers=_HEADERS,
                json={"to": LINE_USER_ID, "messages": [{"type": "text", "text": chunk}]},
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"[ERROR] LINE push失敗: {resp.status_code} {resp.text[:200]}")
                success = False
            time.sleep(1)
        except Exception as e:
            print(f"[ERROR] LINE push例外: {e}")
            success = False
    return success


def reply(reply_token: str, text: str) -> bool:
    """Reply APIで応答。replyTokenは1回・約1分有効。失敗時はpushにフォールバック。"""
    text = text[:4900]
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers=_HEADERS,
            json={"replyToken": reply_token, "messages": [{"type": "text", "text": text}]},
            timeout=30,
        )
        if resp.status_code == 200:
            return True
        print(f"[WARN] reply失敗→pushへ: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[WARN] reply例外→pushへ: {e}")
    return push(text)


def push_quick_reply(text: str, items: list) -> bool:
    """text + クイックリプライ(postback)を1メッセージで push。

    items: [{"label": 表示ラベル, "data": postbackデータ}]。ラベルは20字上限に丸める。
    LINE の quickReply は最大13個。超過分は切り捨て(呼び出し側で警告済みの想定)。
    """
    qr_items = [
        {
            "type": "action",
            "action": {
                "type": "postback",
                "label": it["label"][:20],
                "data": it["data"],
                "displayText": it["label"][:20],
            },
        }
        for it in items[:13]
    ]
    message = {"type": "text", "text": text[:4900], "quickReply": {"items": qr_items}}
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers=_HEADERS,
            json={"to": LINE_USER_ID, "messages": [message]},
            timeout=30,
        )
        if resp.status_code == 200:
            return True
        print(f"[ERROR] quick-reply push失敗: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[ERROR] quick-reply push例外: {e}")
    return False
