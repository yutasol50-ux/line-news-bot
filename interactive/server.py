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
from interactive import media_intake
from interactive import research_async
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
        # まず数十秒待ち、超えたら裏に回して Gmail+LINE要点で届ける(自己昇格)。
        # reply / push は research_async が自前で行う。
        research_async.handle(text, reply_token, "line-owner")
    else:
        line_client.reply(reply_token, dispatch.handle(text, now_iso))


def verify_signature(body: bytes, signature: str) -> bool:
    mac = hmac.new(CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode()
    return hmac.compare_digest(expected, signature or "")


@app.get("/health")
def health():
    return "ok", 200


@app.post("/capture")
def capture():
    """Apple Watch ショートカット用の受け口。

    LINE を経由しないので署名は無い。代わりに CAPTURE_TOKEN で認証する。
    ボディ(JSON)の text を Hermes(Haiku) に渡し、返答を {"reply": ...} で返す。
    Watch から喋る→ここへ POST→腕に返答表示、という口述リモコンの土台。
    """
    server_token = os.environ.get("CAPTURE_TOKEN", "")
    if not server_token:
        # サーバ側にトークン未設定なら、誰でも叩ける穴を開けないよう閉じる。
        abort(503)
    data = request.get_json(silent=True) or {}
    sent_token = request.headers.get("X-Capture-Token") or data.get("token", "")
    if not hmac.compare_digest(str(sent_token), server_token):
        abort(401)
    text = (data.get("text") or "").strip()
    if not text:
        abort(400)
    # LINE と同じ会話部屋(line-owner)を使い、Watch を「LINE会話の遠隔マイク」にする。
    # → Watchで話した続きをLINEで打てる(文脈が繋がる)。
    # 打つ経路と同じ自己昇格: 軽い用事は即答を喋り、重い調査は「調べとくね」を即返して
    # 裏でGmail+LINE要点で届ける(端末の前で固まらせない)。
    reply, route = research_async.handle_capture(text, "line-owner")
    if route == "inline":
        # 会話の記録を LINE トークに残す。腕の通知は消え物なので、永久ログはLINEに置く。
        # push は自前で例外を握って False を返すため、失敗しても /capture の応答は妨げない。
        line_client.push(f"🎙️ Watch:「{text}」\n\n{reply}")
    # route=='async' の時は handle_capture の裏スレッドが完成レポートを push する。
    return {"reply": reply}, 200


@app.post("/webhook")
def webhook():
    body = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")
    if not verify_signature(body, signature):
        abort(400)
    now_iso = datetime.now(JST).isoformat(timespec="seconds")
    payload = request.get_json(silent=True) or {}
    for event in payload.get("events", []):
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        mtype = msg.get("type")
        if mtype not in ("text", "image", "file"):
            continue  # audio 等は未対応(将来STT)
        event_id = event.get("webhookEventId", "")
        # 多重処理の防止は webhookEventId の重複排除だけで行う。
        # isRedelivery では弾かない: 一度も処理できなかったイベントの再送
        # (LINEがくれる再試行)まで捨ててしまい無反応になるため。
        if _seen(event_id):
            print(f"[INFO] 重複イベントをスキップ: {event_id}")
            continue
        reply_token = event.get("replyToken", "")
        # 即200を返してLINEのタイムアウト→再配信を防ぐ。実処理は別スレッドへ。
        if mtype == "text":
            text = msg["text"]
            _spawn(lambda t=text, rt=reply_token: _process(t, rt, now_iso))
        else:  # image / file(PDF) → 取得→読解→Hermesへ
            mid = msg.get("id", "")
            _spawn(lambda i=mid, k=mtype, rt=reply_token: media_intake.handle(i, k, rt))
    return "ok", 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8800)
