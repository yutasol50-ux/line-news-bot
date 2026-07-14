"""LINEに来た音声を保存→即レス→裏でGemini文字起こし→Obsidianドラフト化。
消えない設計: 先に pending/ へ保存。処理成功で削除。落ちても voice_drain が再開。
冪等: message_id を seen で重複排除。"""
import os, json, threading
from pathlib import Path
from interactive import line_media
from interactive import gemini_transcribe
from interactive import obsidian_writer
from shared import line_client

_ROOT = Path(__file__).resolve().parent.parent
PENDING_DIR = os.environ.get("VOICE_PENDING_DIR", str(_ROOT / "data" / "voice" / "pending"))
SEEN_PATH = os.environ.get("VOICE_SEEN_PATH", str(_ROOT / "data" / "voice" / "seen.json"))
INBOX = os.environ.get("OBSIDIAN_VAULT_INBOX",
    "/mnt/c/Users/yuwat/iCloudDrive/iCloud~md~obsidian/vault with claude/_inbox")

_ACK = "受け取った！文字起こしするね📝（少し時間かかるよ）"
_BUSY = "今Geminiが混んでるみたい。あとで自動でもう一回やるね🙏"
_LOCK = threading.Lock()

_EXT = {"audio/m4a":"m4a","audio/x-m4a":"m4a","audio/mp4":"m4a","audio/aac":"aac",
        "audio/mpeg":"mp3","audio/wav":"wav","audio/x-wav":"wav","audio/ogg":"ogg"}

def _ext(content_type): return _EXT.get((content_type or "").lower(), "m4a")

def _load_seen():
    try:
        with open(SEEN_PATH) as f: return set(json.load(f))
    except Exception: return set()

def is_seen(mid): return mid in _load_seen()

def mark_seen(mid):
    with _LOCK:
        s = _load_seen(); s.add(mid)
        os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
        with open(SEEN_PATH, "w") as f: json.dump(sorted(s), f)

def save_pending(message_id, data, content_type):
    os.makedirs(PENDING_DIR, exist_ok=True)
    path = os.path.join(PENDING_DIR, f"{message_id}.{_ext(content_type)}")
    with open(path, "wb") as f: f.write(data)
    return path

def _spawn_thread(fn): threading.Thread(target=fn, daemon=True).start()

def handle(message_id, reply_token, *, fetch=line_media.fetch_content,
           reply=line_client.reply, spawn=_spawn_thread):
    if is_seen(message_id):
        return "duplicate"
    try:
        data, content_type = fetch(message_id)
    except Exception as e:
        print(f"[ERROR] voice_intake fetch: {e}")
        reply(reply_token, "音声の取得でつまずいちゃった。もう一度送ってみて。")
        return "fetch_error"
    save_pending(message_id, data, content_type)
    mark_seen(message_id)
    reply(reply_token, _ACK)
    spawn(lambda: process(message_id))
    return "accepted"

def _find_pending(message_id):
    if not os.path.isdir(PENDING_DIR): return None
    for name in os.listdir(PENDING_DIR):
        if name.rsplit(".",1)[0] == str(message_id):
            return os.path.join(PENDING_DIR, name)
    return None

def process(message_id, *, transcribe=gemini_transcribe.transcribe_long,
            draft=gemini_transcribe.draft_note, write=obsidian_writer.write_draft,
            push=line_client.push, today=None):
    from datetime import datetime, timezone, timedelta
    today = today or datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    path = _find_pending(message_id)
    if not path:
        return "gone"
    try:
        transcript = transcribe(path)
        title, body = draft(transcript)
        md = write(title=title, body=body, transcript=transcript,
                   message_id=message_id, inbox=INBOX, today=today)
    except Exception as e:
        print(f"[ERROR] voice_intake process {message_id}: {e}")
        push(_BUSY)          # pendingは残す=あとでdrainが再開
        return "retry_later"
    os.remove(path)
    head = body.strip().splitlines()[:4]
    push(f"📝『{title}』ノートにしたよ\n" + "\n".join(head) + "\n※あとでPCでOpusがClean upするね")
    return "handled"
