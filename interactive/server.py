#!/usr/bin/env python3
"""LINE Webhook受付。署名検証 → dispatch → reply。"""
import os
import sys
import base64
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, abort

# プロジェクト直下を import パスに追加(shared/ を解決するため)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from interactive import dispatch
from shared import line_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
JST = timezone(timedelta(hours=9))

app = Flask(__name__)


def verify_signature(body: bytes, signature: str) -> bool:
    mac = hmac.new(CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode()
    return hmac.compare_digest(expected, signature or "")


@app.get("/health")
def health():
    return "ok", 200


@app.post("/webhook")
def webhook():
    body = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")
    if not verify_signature(body, signature):
        abort(400)
    now_iso = datetime.now(JST).isoformat(timespec="seconds")
    payload = request.get_json(silent=True) or {}
    for event in payload.get("events", []):
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            text = event["message"]["text"]
            reply_token = event.get("replyToken", "")
            msg = dispatch.handle(text, now_iso)
            line_client.reply(reply_token, msg)
    return "ok", 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8800)
