#!/usr/bin/env python3
"""LINE送信（push）。長文は4900字で分割。"""
import os
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

LINE_ACCESS_TOKEN = os.environ["LINE_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]


def send_line(text: str) -> bool:
    chunks = [text[i:i + 4900] for i in range(0, len(text), 4900)]
    success = True
    for chunk in chunks:
        try:
            resp = requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers={
                    "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"to": LINE_USER_ID, "messages": [{"type": "text", "text": chunk}]},
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"[ERROR] LINE送信失敗: {resp.status_code} {resp.text[:200]}")
                success = False
            time.sleep(1)
        except Exception as e:
            print(f"[ERROR] LINE送信例外: {e}")
            success = False
    return success


if __name__ == "__main__":
    import sys
    msg = sys.argv[1] if len(sys.argv) > 1 else "🤖 LINE秘書 接続テスト"
    print("✅ 成功" if send_line(msg) else "❌ 失敗")
