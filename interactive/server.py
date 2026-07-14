#!/usr/bin/env python3
"""LINE Webhook受付。署名検証 → dispatch → reply。"""
import os
import sys
import base64
import hashlib
import hmac
import secrets
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
from interactive import diary_state
from interactive import diary_collector
from interactive import diary_web
from interactive import approval_parse
from interactive import approval_store
from interactive import approval_reply
from interactive import reminder_store
from interactive import tmux_inject
from interactive import voice_intake
from interactive import voice_drain
from interactive.actions import calendar_add
from shared import line_client
from shared import pushcut_client
from shared import telegram_client
from shared import bark_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
JST = timezone(timedelta(hours=9))


def _startup_drain():
    """起動時に1回だけ、pendingに残った音声を再処理する(cron連動はしない=out of scope)。
    バックログが大きくてもFlask起動をブロックしないようdaemonスレッドで実行。"""
    try:
        n = voice_drain.drain()
        if n:
            print(f"[startup] voice_drain: {n}件を再開")
    except Exception as e:
        print(f"[startup] voice_drain skipped: {e}")


app = Flask(__name__)
app.register_blueprint(diary_web.bp)

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


@app.post("/approval/notify")
def approval_notify():
    """Notificationフックからの通知。承認プロンプトをLINEクイックリプライで push。"""
    server_token = os.environ.get("APPROVAL_TOKEN", "")
    if not server_token:
        abort(503)
    sent = request.headers.get("X-Approval-Token", "")
    if not hmac.compare_digest(str(sent), server_token):
        abort(401)
    data = request.get_json(silent=True) or {}
    parsed = approval_parse.parse(data.get("capture", ""))
    if not parsed:
        return "", 204  # もう承認待ちでない/解析不能 → 何もしない
    token = secrets.token_hex(4)
    now_iso = datetime.now(JST).isoformat(timespec="seconds")
    approval_store.register(
        data.get("pane", ""), data.get("cwd", ""),
        parsed["question"], parsed["choices"], now_iso=now_iso, token=token,
    )
    cwd = data.get("cwd", "")
    header = f"🔐 承認待ち{f' [{cwd}]' if cwd else ''}\n{parsed['question']}"
    items = [{"label": f'{c["key"]}. {c["label"]}', "data": f'approve:{token}:{c["key"]}'}
             for c in parsed["choices"]]
    # 速い通知専用サービス(Bark/Pushcut)を先に飛ばし、遅めのLINEは最後に。
    # Bark: 鍵アイコンで「承認だ」と一目で分かる。未設定なら no-op。
    bark_client.notify(
        "🔐 承認待ち", parsed["question"],
        icon=os.environ.get("BARK_APPROVAL_ICON", ""),
        group="approval",
    )
    # Pushcut: 腕から承認ボタン。動的タイトル/本文はPRO機能なので送らない(名前で鳴らすだけ)。
    pushcut_client.notify()
    # Telegram(Claude Code専用bot): 無料無制限＆Watchで読める。選択肢も本文に含める。
    # ※現状は「通知」まで。OK返信での承認注入は別途ポーラーで対応予定。
    _tg_choices = " / ".join(f'{c["key"]}={c["label"]}' for c in parsed["choices"])
    telegram_client.notify(f"{header}\n\n選択肢: {_tg_choices}")
    # LINE: 遅めだが記録が残る＆クイックリプライ。APPROVAL_NOTIFY_LINE=0 で無効化(Telegram集約時)。
    if os.environ.get("APPROVAL_NOTIFY_LINE", "1") != "0":
        line_client.push_quick_reply(header, items)
    return {"token": token}, 200


def _resolve_and_inject(token: str, key: str):
    """token+key で tmux に注入する共通処理(再検証つき)。
    戻り値 (status, message):
      - "gone"   … その承認はもう無い/解決済み
      - "stale"  … 席で先に答えた(承認プロンプトでない) → resolve のみ
      - "done"   … 注入成功 → resolve
      - "failed" … send-keys 失敗
    LINE/ショートカット双方から使う(ここでは push しない)。
    """
    entry = approval_store.get(token)
    if entry is None:
        return "gone", "この承認はもう解決済みでした。"
    pane = entry["pane"]
    if not approval_parse.is_prompt(tmux_inject.capture(pane)):
        approval_store.resolve(token)
        return "stale", "席で先に答えたようなので、送りませんでした。"
    ok = tmux_inject.send_key(pane, key)
    approval_store.resolve(token)
    label = next((c["label"] for c in entry["choices"] if c["key"] == key), "")
    if ok:
        return "done", f"✅ 送信しました（{key}. {label}）"
    return "failed", "⚠️ 送信に失敗しました。"


def _try_answer_approval(text: str, reply_token: str) -> bool:
    """承認待ちがあり text が Yes/No に解釈できれば、tmuxへ注入して True。
    Apple WatchはLINEボタン(postback)を出せないので、テキスト「OK」等で承認する道。
    承認待ちが無い/承認語でない時は False(=通常のHermes会話へ流す)。"""
    entries = approval_store.pending_entries()
    if not entries:
        return False
    entry = sorted(entries, key=lambda e: e.get("created", ""), reverse=True)[0]
    key = approval_reply.key_for(text, entry.get("choices", []))
    if not key:
        return False

    def _work():
        _status, msg = _resolve_and_inject(entry["token"], key)
        line_client.reply(reply_token, msg)

    _spawn(_work)
    return True


def handle_postback(data: str, user_id: str) -> None:
    """LINEクイックリプライのタップを受けて tmux に注入する(本人・再検証つき)。"""
    if user_id != line_client.LINE_USER_ID:
        return  # 本人以外は無視
    if not data.startswith("approve:"):
        return
    parts = data.split(":")
    if len(parts) != 3:
        return
    _, token, key = parts
    _status, msg = _resolve_and_inject(token, key)
    line_client.push(msg)


@app.get("/approval/pending")
def approval_pending():
    """ショートカット用: 今の承認待ち(最新1件)を返す。X-Approval-Token 認証。"""
    server_token = os.environ.get("APPROVAL_TOKEN", "")
    if not server_token:
        abort(503)
    sent = request.headers.get("X-Approval-Token", "")
    if not hmac.compare_digest(str(sent), server_token):
        abort(401)
    entries = sorted(
        approval_store.pending_entries(),
        key=lambda e: e.get("created", ""), reverse=True,
    )
    current = entries[0] if entries else None
    return {
        "pending": bool(current),
        "current": ({
            "token": current["token"],
            "question": current["question"],
            "choices": current["choices"],
            "cwd": current.get("cwd", ""),
        } if current else None),
        "count": len(entries),
    }, 200


@app.post("/approval/answer")
def approval_answer():
    """ショートカット用: {token, key} を受けて注入。X-Approval-Token 認証。"""
    server_token = os.environ.get("APPROVAL_TOKEN", "")
    if not server_token:
        abort(503)
    sent = request.headers.get("X-Approval-Token", "")
    if not hmac.compare_digest(str(sent), server_token):
        abort(401)
    data = request.get_json(silent=True) or {}
    # key/token は JSON body だけでなくクエリ文字列でも受ける(Pushcut等 Body非対応向け)。
    token = str(data.get("token", "") or request.args.get("token", "")).strip()
    key = str(data.get("key", "") or request.args.get("key", "")).strip()
    if not key:
        abort(400)
    if not token:
        # token 省略時は「今出てる最新の承認」に答える(ショートカット簡易化)。
        entries = sorted(approval_store.pending_entries(),
                         key=lambda e: e.get("created", ""), reverse=True)
        if not entries:
            return {"status": "gone", "message": "承認待ちはありませんでした。"}, 200
        token = entries[0]["token"]
    status, msg = _resolve_and_inject(token, key)
    return {"status": status, "message": msg}, 200


def _reminder_auth(data) -> bool:
    server_token = os.environ.get("REMINDER_TOKEN", "")
    if not server_token:
        abort(503)
    sent = (request.headers.get("X-Reminder-Token", "")
            or str(data.get("token", ""))
            or request.args.get("token", ""))
    return hmac.compare_digest(str(sent), server_token)


def _reminder_target(data) -> str:
    """操作対象の event_id。省略時は「今アクティブなリマインダー」(固定ボタン用)。"""
    eid = str(data.get("event_id", "") or request.args.get("event_id", "")).strip()
    return eid or (reminder_store.get_active() or "")


@app.route("/reminder/done", methods=["GET", "POST"])
def reminder_done():
    """リマインダー完了=予定を削除。Pushcutボタン用(X-Reminder-Token / ?token=)。"""
    data = request.get_json(silent=True) or {}
    if not _reminder_auth(data):
        abort(401)
    eid = _reminder_target(data)
    if not eid:
        return {"status": "gone", "message": "対応するリマインダーがないよ。"}, 200
    try:
        calendar_add.delete_event(eid)
    except Exception as e:
        print(f"[ERROR] reminder_done delete: {e}")
    reminder_store.clear(eid)
    return {"status": "done", "message": "完了にしたよ👍"}, 200


@app.route("/reminder/snooze", methods=["GET", "POST"])
def reminder_snooze():
    """スヌーズ=予定を minutes 分先へ移動し、既配達を外して再発火させる。既定10分。"""
    data = request.get_json(silent=True) or {}
    if not _reminder_auth(data):
        abort(401)
    eid = _reminder_target(data)
    if not eid:
        return {"status": "gone", "message": "対応するリマインダーがないよ。"}, 200
    try:
        minutes = int(data.get("minutes", 0) or request.args.get("minutes", 0) or 10)
    except (ValueError, TypeError):
        minutes = 10
    new_start = (datetime.now(JST) + timedelta(minutes=minutes)).replace(
        microsecond=0).isoformat()
    try:
        calendar_add.reschedule(eid, new_start)
    except Exception as e:
        print(f"[ERROR] reminder_snooze reschedule: {e}")
    reminder_store.clear(eid)  # 既配達フラグを外す→新時刻の到来で見張りが再発火
    return {"status": "snoozed", "message": f"{minutes}分後にまた鳴らすね⏰"}, 200


# --- 音声ファイル添付の判定 --------------------------------------------------
# LINEの type=file は拡張子を問わず届く。ユーザーの実運用は「長尺録音をファイル共有」
# なので、拡張子が音声系なら voice_intake へ、それ以外(PDF等)は media_intake へ。
_AUDIO_FILE_EXTS = (".m4a", ".mp3", ".wav", ".aac", ".ogg", ".m4b", ".mp4", ".caf", ".opus", ".flac")


def _is_audio_file(msg):
    return (msg.get("fileName") or "").lower().endswith(_AUDIO_FILE_EXTS)


@app.post("/webhook")
def webhook():
    body = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")
    if not verify_signature(body, signature):
        abort(400)
    now_iso = datetime.now(JST).isoformat(timespec="seconds")
    payload = request.get_json(silent=True) or {}
    for event in payload.get("events", []):
        if event.get("type") == "postback":
            event_id = event.get("webhookEventId", "")
            if _seen(event_id):
                continue
            uid = event.get("source", {}).get("userId", "")
            pb = event.get("postback", {}).get("data", "")
            _spawn(lambda d=pb, u=uid: handle_postback(d, u))
            continue
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        mtype = msg.get("type")
        if mtype not in ("text", "image", "file", "audio"):
            continue  # sticker/location 等は未対応
        event_id = event.get("webhookEventId", "")
        # 多重処理の防止は webhookEventId の重複排除だけで行う。
        # isRedelivery では弾かない: 一度も処理できなかったイベントの再送
        # (LINEがくれる再試行)まで捨ててしまい無反応になるため。
        if _seen(event_id):
            print(f"[INFO] 重複イベントをスキップ: {event_id}")
            continue
        reply_token = event.get("replyToken", "")
        # 日記モード中は日記コレクタへ(通常Hermes/画像intakeへは進ませない)
        if diary_state.is_active():
            if mtype == "text":
                t = msg["text"]
                _spawn(lambda tx=t, rt=reply_token: diary_collector.handle_text(tx, rt))
            elif mtype == "audio" or (mtype == "file" and _is_audio_file(msg)):
                # 日記モード中でも音声(hold-mic or ファイル添付)はObsidianノートへ
                mid = msg.get("id", "")
                _spawn(lambda i=mid, rt=reply_token: voice_intake.handle(i, rt))
            else:  # image / 非音声file
                mid = msg.get("id", "")
                _spawn(lambda i=mid, rt=reply_token: diary_collector.handle_photo(i, rt))
            continue
        if mtype == "text" and msg["text"].strip() == "日記":
            _spawn(lambda rt=reply_token: diary_collector.start_manual(rt))
            continue
        # 承認待ちがあれば「OK」等のテキスト返信を承認として横取り(Watch対応)。
        if mtype == "text" and _try_answer_approval(msg["text"], reply_token):
            continue
        # 即200を返してLINEのタイムアウト→再配信を防ぐ。実処理は別スレッドへ。
        if mtype == "text":
            text = msg["text"]
            _spawn(lambda t=text, rt=reply_token: _process(t, rt, now_iso))
        elif mtype == "audio" or (mtype == "file" and _is_audio_file(msg)):
            # 音声(hold-mic or ファイル添付) → 保存/文字起こし/Obsidianドラフト化
            mid = msg.get("id", "")
            _spawn(lambda i=mid, rt=reply_token: voice_intake.handle(i, rt))
        else:  # image / 非音声file(PDF等) → 取得→読解→Hermesへ
            mid = msg.get("id", "")
            _spawn(lambda i=mid, k=mtype, rt=reply_token: media_intake.handle(i, k, rt))
    return "ok", 200


if __name__ == "__main__":
    threading.Thread(target=_startup_drain, daemon=True).start()
    app.run(host="127.0.0.1", port=8800)
