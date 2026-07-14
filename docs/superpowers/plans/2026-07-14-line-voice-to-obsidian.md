# LINE音声 → Gemini文字起こし → Obsidian 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LINEに送った音声を、Geminiで文字起こし＆下書き整形し、Obsidian vaultの`_inbox/`にドラフトノートとして自動保存する（後日Opusが清書）。

**Architecture:** 既存 `line-news-bot`（Flask webhook + スレッドspawn）に音声の口を開ける。到着時に音声を`pending/`へ即保存してLINEへ即レス（消えない＆丸投げ）。裏でGeminiが文字起こし→下書き→vault書き込み→`push()`で完了通知。途中で落ちても`pending/`が残り、起動時drainが再開。冪等性はmessage_idで担保。

**Tech Stack:** Python 3.12, Flask, requests, ffmpeg(subprocess), Gemini REST API (File API + generateContent), pytest。

## Global Constraints

- 文字起こし＝Gemini、清書＝後日Opus（本計画では清書は自動化しない）。
- APIキーは環境変数 `GEMINI_API_KEY`（`.env`で供給）。文字起こしモデルは `gemini-2.5-flash`（503/429時 `gemini-2.5-flash-lite` フォールバック）。
- vault書き込み先は `.env` の `OBSIDIAN_VAULT_INBOX`（既定: `/mnt/c/Users/yuwat/iCloudDrive/iCloud~md~obsidian/vault with claude/_inbox`）。
- 完了通知は `line_client.push()`（reply_tokenは失効するため）。到着即レスのみ `line_client.reply()`。
- 依存は関数引数で注入しテスト可能に（`media_intake.py`に倣う）。外部I/O（HTTP/ffmpeg/ファイル/LINE）はテストで必ずモック。
- 20分超の音声はffmpegで20分チャンクに分割して文字起こし→連結。
- DRY / YAGNI / TDD / 各タスク末尾でコミット。

---

## ファイル構成

- Create `interactive/gemini_transcribe.py` — Gemini文字起こし＆下書き整形。`transcribe(path)`, `transcribe_long(path)`, `draft_note(transcript)`。
- Create `interactive/obsidian_writer.py` — `write_draft(...)` で`_inbox/`に`.md`保存。
- Create `interactive/voice_intake.py` — オーケストレータ。`save_pending`, `handle`, `process`, seen(dedup)。
- Create `interactive/voice_drain.py` — `pending/`の未完了を再開。
- Modify `interactive/server.py` — `audio`を受理し`voice_intake.handle`へ。起動時に`voice_drain.drain()`。
- Create tests: `tests/test_gemini_transcribe.py`, `tests/test_obsidian_writer.py`, `tests/test_voice_intake.py`, `tests/test_voice_drain.py`。
- Config: `.env`に`OBSIDIAN_VAULT_INBOX`追加、`GEMINI_API_KEY`がサービスに渡ることを確認。
- Data: `data/voice/pending/`, `data/voice/seen.json`（`.gitignore`に追加）。

---

### Task 1: gemini_transcribe（文字起こしコア）

**Files:**
- Create: `interactive/gemini_transcribe.py`
- Test: `tests/test_gemini_transcribe.py`
- 参照: `~/tool/gemini_transcribe.py`（File API・503リトライの原型）

**Interfaces:**
- Produces:
  - `transcribe(path: str, *, post=requests.post, get=requests.get, sleep=time.sleep) -> str`
  - `transcribe_long(path: str, *, split=_ffmpeg_split, transcribe=transcribe, chunk_sec=1200) -> str`
  - `draft_note(transcript: str, *, post=requests.post) -> tuple[str, str]`  # (title, body)

- [ ] **Step 1: 失敗するテストを書く（リトライ→フォールバック→本文抽出）**

```python
# tests/test_gemini_transcribe.py
import interactive.gemini_transcribe as gt

class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status; self._p = payload or {}; self.headers = headers or {}
    def json(self): return self._p
    @property
    def text(self): return str(self._p)
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(self.status_code)

def test_transcribe_retries_then_succeeds(monkeypatch, tmp_path):
    f = tmp_path / "a.m4a"; f.write_bytes(b"x" * 10)  # 小さい=inline
    calls = {"n": 0}
    def fake_post(url, **kw):
        if "generateContent" in url:
            calls["n"] += 1
            if calls["n"] == 1:
                return _Resp(503)
            return _Resp(200, {"candidates":[{"content":{"parts":[{"text":"こんにちは"}]}}]})
        return _Resp(200, {})
    text = gt.transcribe(str(f), post=fake_post, sleep=lambda s: None)
    assert text == "こんにちは"
    assert calls["n"] == 2  # 1回503→リトライで成功
```

- [ ] **Step 2: 失敗を確認**

Run: `cd ~/line/line-news-bot && python -m pytest tests/test_gemini_transcribe.py -v`
Expected: FAIL（module/関数が無い）

- [ ] **Step 3: 実装（`~/tool/gemini_transcribe.py`を移植し関数化）**

`~/tool/gemini_transcribe.py` の内容を土台に、以下の公開関数を持つモジュールにする（`main`は不要）:
- `transcribe(path, *, post=requests.post, get=requests.get, sleep=time.sleep)`:
  - `< 7MB` は inline（base64）、それ以上は File API（`_upload_file`）。
  - `generateContent` を `gemini-2.5-flash` → `gemini-2.5-flash-lite` の順で、各5回まで `429/500/503` に指数バックオフ（`5 * 2**attempt` 秒、`sleep()`使用）。
  - `generationConfig` に `{"temperature":0.0, "maxOutputTokens": 65536}` を指定（長尺の尻切れ防止）。
  - 本文は `candidates[0].content.parts[*].text` を連結して返す。
- `_ffmpeg_split(path, chunk_sec, workdir) -> list[str]`: `ffmpeg -i <path> -f segment -segment_time <chunk_sec> -c copy -reset_timestamps 1 <workdir>/chunk_%03d.<ext>` を `subprocess.run`。生成チャンクのパス昇順リストを返す。
- `transcribe_long(path, *, split=_ffmpeg_split, transcribe=transcribe, chunk_sec=1200)`: 分割→各チャンク`transcribe`→`"\n".join()`。分割が1個以下なら直接`transcribe(path)`。
- `draft_note(transcript, *, post=requests.post)`: `gemini-2.5-flash` に「1行目=タイトル、続けて要点(3-5)と見出し付き本文の"下書き"を作れ。要約しすぎない」プロンプトで投げ、戻り全文の1行目をtitle、残りをbodyとして返す。503リトライは`transcribe`と同じ方針。

（`post/get/sleep` を引数で受けてテスト可能にすること。既定は `requests.post` 等。）

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest tests/test_gemini_transcribe.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add interactive/gemini_transcribe.py tests/test_gemini_transcribe.py
git commit -m "feat(voice): Gemini文字起こしコア(transcribe/long/draft)"
```

---

### Task 2: obsidian_writer（vaultへドラフト保存）

**Files:**
- Create: `interactive/obsidian_writer.py`
- Test: `tests/test_obsidian_writer.py`

**Interfaces:**
- Produces: `write_draft(title: str, body: str, transcript: str, message_id: str, *, inbox: str, today: str) -> str`（保存した`.md`の絶対パスを返す）

- [ ] **Step 1: 失敗するテスト**

```python
# tests/test_obsidian_writer.py
import interactive.obsidian_writer as ow

def test_write_draft_creates_md_with_frontmatter(tmp_path):
    p = ow.write_draft(
        title="散歩メモ AIとお金",
        body="## 要点\n- a\n- b\n",
        transcript="生の文字起こし全文",
        message_id="12345",
        inbox=str(tmp_path),
        today="2026-07-14",
    )
    assert p.endswith(".md")
    text = (tmp_path / __import__("os").path.basename(p)).read_text()
    assert "status: draft" in text
    assert "message_id: 12345" in text
    assert "散歩メモ AIとお金" in text
    assert "## 全文（Gemini文字起こし）" in text
    assert "生の文字起こし全文" in text
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_obsidian_writer.py -v`
Expected: FAIL

- [ ] **Step 3: 実装**

```python
# interactive/obsidian_writer.py
import os, re

def _slug(title, today):
    s = re.sub(r"[\\/:*?\"<>|\n\r]", "", title).strip()[:40] or "voicememo"
    return f"{today}-{s}"

def write_draft(title, body, transcript, message_id, *, inbox, today):
    os.makedirs(inbox, exist_ok=True)
    base = _slug(title, today)
    path = os.path.join(inbox, base + ".md")
    n = 2
    while os.path.exists(path):
        path = os.path.join(inbox, f"{base}-{n}.md"); n += 1
    fm = (
        "---\n"
        "tags: [voicememo, 要清書]\n"
        f"created: {today}\n"
        "source: LINE音声 → Gemini(自動下書き)\n"
        "status: draft\n"
        f"message_id: {message_id}\n"
        "---\n\n"
    )
    content = f"{fm}# {title}\n\n{body}\n\n## 全文（Gemini文字起こし）\n\n{transcript}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
```

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest tests/test_obsidian_writer.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add interactive/obsidian_writer.py tests/test_obsidian_writer.py
git commit -m "feat(voice): Obsidian _inbox へのドラフト保存"
```

---

### Task 3: voice_intake（保存→即レス→裏処理のオーケストレータ）

**Files:**
- Create: `interactive/voice_intake.py`
- Test: `tests/test_voice_intake.py`
- 参照: `interactive/media_intake.py`（依存注入の型）

**Interfaces:**
- Consumes: `line_media.fetch_content`, `gemini_transcribe.transcribe_long`, `gemini_transcribe.draft_note`, `obsidian_writer.write_draft`, `line_client.reply/push`
- Produces:
  - `PENDING_DIR: str`, `SEEN_PATH: str`（`data/voice/`配下、`.env`/既定で解決）
  - `save_pending(message_id, data, content_type) -> str`
  - `mark_seen(message_id)`, `is_seen(message_id) -> bool`
  - `handle(message_id, reply_token, *, fetch=..., reply=..., spawn=...) -> str`
  - `process(message_id, *, transcribe=..., draft=..., write=..., push=..., today=...) -> str`

- [ ] **Step 1: 失敗するテスト（handleは即レス＆pending保存、二重はスキップ）**

```python
# tests/test_voice_intake.py
import os, interactive.voice_intake as vi

def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(vi, "PENDING_DIR", str(tmp_path / "pending"))
    monkeypatch.setattr(vi, "SEEN_PATH", str(tmp_path / "seen.json"))

def test_handle_saves_pending_and_replies(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    replies, spawned = [], []
    def fake_fetch(mid): return (b"audiobytes", "audio/m4a")
    vi.handle("100", "RT",
              fetch=fake_fetch,
              reply=lambda rt, t: replies.append((rt, t)),
              spawn=lambda fn: spawned.append(fn))
    assert os.path.exists(os.path.join(vi.PENDING_DIR, "100.m4a"))
    assert replies and replies[0][0] == "RT"
    assert spawned  # 裏処理が積まれた

def test_handle_dedup_skips_seen(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    vi.mark_seen("100")
    spawned = []
    r = vi.handle("100", "RT", fetch=lambda m: (b"x","audio/m4a"),
                  reply=lambda rt,t: None, spawn=lambda fn: spawned.append(fn))
    assert r == "duplicate"
    assert not spawned

def test_process_transcribes_and_writes(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    os.makedirs(vi.PENDING_DIR, exist_ok=True)
    fp = os.path.join(vi.PENDING_DIR, "100.m4a"); open(fp,"wb").write(b"x")
    pushed = []
    r = vi.process("100",
        transcribe=lambda p: "全文テキスト",
        draft=lambda t: ("タイトル", "## 要点\n- x\n"),
        write=lambda **kw: "/vault/_inbox/2026-07-14-タイトル.md",
        push=lambda t: pushed.append(t),
        today="2026-07-14")
    assert r == "handled"
    assert not os.path.exists(fp)   # 完了でpending削除
    assert pushed and "タイトル" in pushed[0]
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_voice_intake.py -v`
Expected: FAIL

- [ ] **Step 3: 実装**

```python
# interactive/voice_intake.py
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
```

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest tests/test_voice_intake.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add interactive/voice_intake.py tests/test_voice_intake.py
git commit -m "feat(voice): 保存→即レス→裏でGemini→Obsidianのオーケストレータ"
```

---

### Task 4: voice_drain（中断分の再開）

**Files:**
- Create: `interactive/voice_drain.py`
- Test: `tests/test_voice_drain.py`

**Interfaces:**
- Consumes: `voice_intake.PENDING_DIR`, `voice_intake.process`
- Produces: `drain(*, process=voice_intake.process) -> int`（再開した件数）

- [ ] **Step 1: 失敗するテスト**

```python
# tests/test_voice_drain.py
import os, interactive.voice_drain as vd, interactive.voice_intake as vi

def test_drain_reprocesses_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(vi, "PENDING_DIR", str(tmp_path))
    open(os.path.join(str(tmp_path), "1.m4a"), "wb").write(b"x")
    open(os.path.join(str(tmp_path), "2.m4a"), "wb").write(b"x")
    done = []
    n = vd.drain(process=lambda mid: done.append(mid))
    assert n == 2 and set(done) == {"1", "2"}
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_voice_drain.py -v`
Expected: FAIL

- [ ] **Step 3: 実装**

```python
# interactive/voice_drain.py
"""起動時/定期に、未完了(pending/に残った)音声を再処理する。"""
import os
from interactive import voice_intake

def drain(*, process=voice_intake.process):
    d = voice_intake.PENDING_DIR
    if not os.path.isdir(d): return 0
    mids = sorted({name.rsplit(".",1)[0] for name in os.listdir(d)})
    for mid in mids:
        try:
            process(mid)
        except Exception as e:
            print(f"[ERROR] voice_drain {mid}: {e}")
    return len(mids)

if __name__ == "__main__":
    print(f"drained {drain()}")
```

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest tests/test_voice_drain.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add interactive/voice_drain.py tests/test_voice_drain.py
git commit -m "feat(voice): 中断した音声処理を起動時/定期に再開するdrain"
```

---

### Task 5: server.py 配線（audio受理＋起動時drain）

**Files:**
- Modify: `interactive/server.py`（import追加、`mtype`分岐、起動時drain）
- Test: `tests/test_server.py`（既存に追記）

**Interfaces:**
- Consumes: `voice_intake.handle`, `voice_drain.drain`

- [ ] **Step 1: 失敗するテスト（audioメッセージで voice_intake.handle が呼ばれる）**

```python
# tests/test_server.py に追記
def test_audio_message_routes_to_voice_intake(monkeypatch, client, valid_headers):
    import interactive.server as srv
    called = {}
    monkeypatch.setattr(srv.voice_intake, "handle",
        lambda mid, rt, **k: called.setdefault("mid", mid))
    # spawnを同期実行に(テスト用)
    monkeypatch.setattr(srv, "_spawn", lambda fn: fn())
    body = srv_json_event({"type":"message","message":{"type":"audio","id":"999"},
                           "replyToken":"RT","webhookEventId":"E1"})
    client.post("/webhook", data=body, headers=valid_headers(body))
    assert called.get("mid") == "999"
```
（`client`/`valid_headers`/`srv_json_event` は既存テストのヘルパに合わせる。無ければ既存 `test_server.py` の署名生成・イベント生成ヘルパを再利用。）

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_server.py::test_audio_message_routes_to_voice_intake -v`
Expected: FAIL

- [ ] **Step 3: 実装（server.pyを編集）**

1. import追加（他importの並びに）:
```python
from interactive import voice_intake
from interactive import voice_drain
```
2. `mtype` 受理リストに `audio` を追加:
```python
        if mtype not in ("text", "image", "file", "audio"):
            continue  # それ以外(sticker/location等)は未対応
```
3. 末尾の分岐（image/file の elif の前）に audio を追加:
```python
        elif mtype == "audio":
            mid = msg.get("id", "")
            _spawn(lambda i=mid, rt=reply_token: voice_intake.handle(i, rt))
        else:  # image / file(PDF) → 取得→読解→Hermesへ
            mid = msg.get("id", "")
            _spawn(lambda i=mid, k=mtype, rt=reply_token: media_intake.handle(i, k, rt))
```
（既存の `if mtype == "text": ... else: media_intake` を `if text / elif audio / else media_intake` の3分岐へ。）
4. 起動時drain（`load_dotenv(...)` の直後あたり、モジュール読み込み時に1回）:
```python
try:
    _n = voice_drain.drain()
    if _n: print(f"[startup] voice_drain: {_n}件を再開")
except Exception as _e:
    print(f"[startup] voice_drain skipped: {_e}")
```

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest tests/test_server.py -v`
Expected: PASS（既存テストも緑のまま）

- [ ] **Step 5: コミット**

```bash
git add interactive/server.py tests/test_server.py
git commit -m "feat(voice): server webhookでaudioを受理し起動時drainを実行"
```

---

### Task 6: 設定・データ配置・実機E2E検証

**Files:**
- Modify: `.env`（`OBSIDIAN_VAULT_INBOX`追加。`GEMINI_API_KEY`が無ければ追記）
- Modify: `.gitignore`（`data/voice/`追加）
- Create: `data/voice/pending/.gitkeep`

- [ ] **Step 1: .env と .gitignore**

`.env` に追記（値は環境に合わせて）:
```
OBSIDIAN_VAULT_INBOX=/mnt/c/Users/yuwat/iCloudDrive/iCloud~md~obsidian/vault with claude/_inbox
GEMINI_API_KEY=＜既存のキー＞
```
`.gitignore` に追記: `data/voice/`

- [ ] **Step 2: systemdサービスから /mnt/c とキーが見えるか検証**

Run:
```bash
systemctl --user show secretary-webhook -p Environment 2>/dev/null | tr ' ' '\n' | grep -i gemini || echo "サービスにGEMINI_API_KEYが無い→.env経由か確認"
python - <<'PY'
import os; p="/mnt/c/Users/yuwat/iCloudDrive/iCloud~md~obsidian/vault with claude/_inbox"
os.makedirs(p, exist_ok=True); open(p+"/.probe","w").write("ok"); print("write OK:", p)
PY
```
Expected: `write OK` が出る（WSLからvaultへ書ける）。書けなければパス/権限を修正。

- [ ] **Step 3: 短い音声で実機E2E**

1. `data/voice/pending/short.m4a` に手元の短い音声を置く（または既存 `/mnt/c/.../iCloudDrive/新規録音 39.m4a` を数十秒に切って使用）。
2. Run:
```bash
cd ~/line/line-news-bot && python -c "from interactive import voice_intake as vi; print(vi.process('short'))"
```
3. Expected: `handled`。vaultの `_inbox/` に `.md` が生成され、frontmatterに `status: draft`、本文にタイトル＋要点＋全文がある。Gemini混雑時は `retry_later`（pendingに残る）→時間をおいて再実行。

- [ ] **Step 4: サービス再起動でdrainが動くか**

Run:
```bash
# pendingに1件置いた状態で
systemctl --user restart secretary-webhook 2>/dev/null || (pkill -f interactive/server.py; )
journalctl --user -u secretary-webhook -n 20 --no-pager 2>/dev/null | grep -i drain || echo "ログ確認: [startup] voice_drain"
```
Expected: 起動ログに `voice_drain: N件を再開`。

- [ ] **Step 5: コミット**

```bash
git add .gitignore data/voice/.gitkeep 2>/dev/null; git add -A
git commit -m "chore(voice): 設定・データ配置・E2E検証手順"
```

---

## 自己レビュー結果（spec対応）

- 音声取得: Task5(server)→Task3(handle/fetch)。✅
- 文字起こし＋長尺分割: Task1。✅
- 下書き整形: Task1(`draft_note`)。✅
- Obsidian `_inbox` ドラフト: Task2。✅
- 即レス＆完了push: Task3（reply=即, push=完了）。✅
- 消えない/再開: Task3(save_pending先行)＋Task4(drain)＋Task5(起動時)。✅
- 冪等(message_id): Task3(seen)＋Task5(webhookEventId既存)。✅
- 503リトライ/枠超過通知: Task1(バックオフ)＋Task3(`_BUSY`push)。✅
- 設定/検証: Task6。✅
- 非スコープ（テキスト/画像/雑談/清書自動化）は着手しない。✅

## 未確定（実装時に確定）
- systemd(WSL)から `/mnt/c` 書き込み可否 → Task6-Step2で検証。不可なら一旦WSL側にvaultミラーを置きrsync等、別途検討。
- 既存 `tests/test_server.py` のヘルパ名 → 実物に合わせて Task5 テストを調整。
