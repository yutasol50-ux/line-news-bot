#!/usr/bin/env python3
"""LINE Webhook受付。署名検証 → dispatch → reply。"""
import os
import sys
import base64
import hashlib
import hmac
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, abort

# プロジェクト直下を import パスに追加(shared/ を解決するため)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from interactive import dispatch
from interactive import hermes_brain
from shared import line_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
JST = timezone(timedelta(hours=9))

app = Flask(__name__)

# --- 重複処理の防止 ---------------------------------------------------------
# LINEは応答が遅い/失敗すると同じイベントを再配信する(at-least-once)。
# webhookEventId で冪等化し、同じ予定が何度も登録されるのを防ぐ。
_MAX_SEEN = 2000
_seen_ids: list[str] = []
_seen_set: set[str] = set()
_seen_lock = threading.Lock()


def _seen(event_id: str) -> bool:
    """未処理なら記録して False、処理済みなら True を返す(IDが空なら常に False)。"""
    if not event_id:
        return False
    with _seen_lock:
        if event_id in _seen_set:
            return True
        _seen_set.add(event_id)
        _seen_ids.append(event_id)
        if len(_seen_ids) > _MAX_SEEN:
            _seen_set.discard(_seen_ids.pop(0))
    return False


def _spawn(fn) -> None:
    """重い処理をバックグラウンドで実行(テストでは同期実行に差し替える)。"""
    threading.Thread(target=fn, daemon=True).start()


def _process(text: str, reply_token: str, now_iso: str) -> None:
    if os.environ.get("HERMES_BRAIN", "").lower() in ("on", "1", "true"):
        msg = hermes_brain.ask(text, "line-owner")
    else:
        msg = dispatch.handle(text, now_iso)
    line_client.reply(reply_token, msg)


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
        if event.get("type") != "message" or event.get("message", {}).get("type") != "text":
            continue
        event_id = event.get("webhookEventId", "")
        # 多重登録の防止は webhookEventId の重複排除だけで行う。
        # isRedelivery では弾かない: 一度も処理できなかったイベントの再送
        # (LINEがくれる再試行)まで捨ててしまい無反応になるため。
        if _seen(event_id):
            print(f"[INFO] 重複イベントをスキップ: {event_id}")
            continue
        text = event["message"]["text"]
        reply_token = event.get("replyToken", "")
        # 即200を返してLINEのタイムアウト→再配信を防ぐ。実処理は別スレッドへ。
        _spawn(lambda t=text, rt=reply_token: _process(t, rt, now_iso))
    return "ok", 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8800)
