"""LINEに来た音声を保存→即レス→裏でGemini文字起こし→Obsidianドラフト化。
消えない設計: 先に pending/ へ保存。処理成功で削除。落ちても voice_drain が再開。
冪等: message_id を seen で重複排除。
永久失敗対策: 試行回数が上限を超えたら failed/ へ隔離し、drain対象から外す。"""
import os, json, threading, tempfile
from pathlib import Path
from interactive import line_media
from interactive import gemini_transcribe
from interactive import obsidian_writer
from shared import line_client

_ROOT = Path(__file__).resolve().parent.parent
PENDING_DIR = os.environ.get("VOICE_PENDING_DIR", str(_ROOT / "data" / "voice" / "pending"))
FAILED_DIR = os.environ.get("VOICE_FAILED_DIR", str(_ROOT / "data" / "voice" / "failed"))
SEEN_PATH = os.environ.get("VOICE_SEEN_PATH", str(_ROOT / "data" / "voice" / "seen.json"))
ATTEMPTS_PATH = os.environ.get("VOICE_ATTEMPTS_PATH", str(_ROOT / "data" / "voice" / "attempts.json"))
INBOX = os.environ.get("OBSIDIAN_VAULT_INBOX",
    "/mnt/c/Users/yuwat/iCloudDrive/iCloud~md~obsidian/vault with claude/_inbox")

_ACK = "受け取った！文字起こしするね📝（少し時間かかるよ）"
_BUSY = "今Geminiが混んでるみたい。あとで自動でもう一回やるね🙏"
_FAILED = "⚠️ この音声はうまく処理できなかった。ファイルは保管してあるよ（data/voice/failed/）"
_LOCK = threading.Lock()

# systemd Restart=always 下で無限リトライ+_BUSYスパム+クォータ浪費を防ぐための上限。
# 破損音声や終日クォータ切れでも、これを超えたらfailed/へ隔離して静かにする。
MAX_ATTEMPTS = 5
# server.py の _MAX_SEEN と同じ規約(直近N件だけ保持)。
_MAX_SEEN = 2000

_EXT = {"audio/m4a":"m4a","audio/x-m4a":"m4a","audio/mp4":"m4a","audio/aac":"aac",
        "audio/mpeg":"mp3","audio/wav":"wav","audio/x-wav":"wav","audio/ogg":"ogg"}

def _ext(content_type): return _EXT.get((content_type or "").lower(), "m4a")

def _atomic_write_json(path, obj):
    """壊れた書き込み(kill/クラッシュ)で既存ファイルを破損させないよう、
    同じディレクトリに書いてから os.replace で原子的に差し替える。"""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise

def _load_seen_ids():
    """seen済みidを挿入順(古い→新しい)のリストで返す。壊れた/存在しないファイルは空扱い。"""
    try:
        with open(SEEN_PATH) as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    seen, ids = set(), []
    for mid in data:
        if mid not in seen:
            seen.add(mid)
            ids.append(mid)
    return ids

def _save_seen_ids(ids):
    """直近 _MAX_SEEN 件だけ残す(古い方から捨てる)。"""
    if len(ids) > _MAX_SEEN:
        ids = ids[-_MAX_SEEN:]
    _atomic_write_json(SEEN_PATH, ids)

def _load_seen():
    return set(_load_seen_ids())

def is_seen(mid): return mid in _load_seen()

def mark_seen(mid):
    with _LOCK:
        ids = _load_seen_ids()
        if mid not in ids:
            ids.append(mid)
        _save_seen_ids(ids)

def claim(mid):
    """原子的なcheck-and-set。既にseen済みならFalse、未見なら即マークしてTrueを返す。"""
    with _LOCK:
        ids = _load_seen_ids()
        if mid in ids:
            return False
        ids.append(mid)
        _save_seen_ids(ids)
        return True

def unmark_seen(mid):
    """claim後にfetch失敗した場合のロールバック。再送で再度claimできるようにする。"""
    with _LOCK:
        ids = _load_seen_ids()
        if mid in ids:
            ids.remove(mid)
        _save_seen_ids(ids)

def _load_attempts():
    try:
        with open(ATTEMPTS_PATH) as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}

def _incr_attempts(mid):
    """message_id の失敗回数を1つ増やして保存し、増やした後の回数を返す。"""
    with _LOCK:
        d = _load_attempts()
        d[mid] = d.get(mid, 0) + 1
        _atomic_write_json(ATTEMPTS_PATH, d)
        return d[mid]

def _clear_attempts(mid):
    with _LOCK:
        d = _load_attempts()
        if mid in d:
            del d[mid]
            _atomic_write_json(ATTEMPTS_PATH, d)

def _quarantine(path):
    """恒久失敗と判断したpendingファイルを failed/ へ移す(drainの対象外にする)。"""
    os.makedirs(FAILED_DIR, exist_ok=True)
    dest = os.path.join(FAILED_DIR, os.path.basename(path))
    os.replace(path, dest)
    return dest

def save_pending(message_id, data, content_type):
    os.makedirs(PENDING_DIR, exist_ok=True)
    path = os.path.join(PENDING_DIR, f"{message_id}.{_ext(content_type)}")
    with open(path, "wb") as f: f.write(data)
    return path

def _spawn_thread(fn): threading.Thread(target=fn, daemon=True).start()

def handle(message_id, reply_token, *, fetch=line_media.fetch_content,
           reply=line_client.reply, spawn=_spawn_thread):
    if not claim(message_id):
        return "duplicate"
    try:
        data, content_type = fetch(message_id)
        save_pending(message_id, data, content_type)
    except Exception as e:
        print(f"[ERROR] voice_intake fetch: {e}")
        unmark_seen(message_id)
        reply(reply_token, "音声の取得でつまずいちゃった。もう一度送ってみて。")
        return "fetch_error"
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
        print(f"[voice_intake] wrote {md}")
    except Exception as e:
        print(f"[ERROR] voice_intake process {message_id}: {e}")
        attempts = _incr_attempts(message_id)
        if attempts >= MAX_ATTEMPTS:
            # 恒久失敗(壊れた音声/終日クォータ切れ等)とみなし、これ以上は
            # 起動のたびに再試行して_BUSYを撒いたりクォータを消費したりしない。
            dest = _quarantine(path)
            _clear_attempts(message_id)
            print(f"[voice_intake] quarantined {message_id} -> {dest} after {attempts} attempts")
            push(_FAILED)
            return "failed"
        push(_BUSY)          # pendingは残す=あとでdrainが再開
        return "retry_later"
    _clear_attempts(message_id)  # 成功したので過去の失敗カウントは片付ける
    # known limitation: write_draft成功直後〜os.remove(path)の間でプロセスが落ちると、
    # 次回drainで同じmessage_idのpendingが残っていて再度write_draftが走り、
    # Obsidianに重複ノートができうる。v1では許容する(手動マージで対処)。
    try:
        os.remove(path)
    except FileNotFoundError:
        pass  # 並行removeで既に消えていても問題ない
    head = body.strip().splitlines()[:4]
    push(f"📝『{title}』ノートにしたよ\n" + "\n".join(head) + "\n※あとでPCでOpusがClean upするね")
    return "handled"
