# LINE 写真/PDF 入力の開通 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LINEに共有した写真/PDFを、Hermes(Haiku)がネイティブ読解して要点整理し、LINEに返す配管を1本通す。

**Architecture:** LINE webhookが image/file メッセージを検出 → line-news-bot側ハンドラが ①LINE content APIでメディア本体を取得 → ②Anthropic Messages APIでHaikuに読み取らせ「テキスト」に変換 → ③そのテキストを既存の自己昇格ディスパッチャ(`research_async.handle`)経由でHermesに渡す。**Hermesにはファイル/ディスク権限を一切与えず、常にテキストだけを渡す**（既存の設計方針）。音声(STT)は本計画のスコープ外（Mac mini後）。

**Tech Stack:** Python 3, Flask, `requests`直叩き(Anthropic Messages API / LINE Messaging API), pytest, monkeypatchによるTDD。既存 `interactive/summarize.py` と同じAnthropic直叩きパターンを踏襲。

## Global Constraints

- 対象ディレクトリ: `/home/yuta/line/line-news-bot/`。テスト実行は `cd /home/yuta/line/line-news-bot && ./venv/bin/python3 -m pytest`。
- Anthropicモデルは `claude-haiku-4-5` 固定。エンドポイント `https://api.anthropic.com/v1/messages`、ヘッダ `x-api-key` + `anthropic-version: 2023-06-01`。鍵は `~/.hermes/.env` の `ANTHROPIC_API_KEY`（`load_dotenv(Path.home()/".hermes"/".env")` で読む。`summarize.py` と同一）。
- LINEトークンは `~/line/line-news-bot/.env` の `LINE_ACCESS_TOKEN`（`shared/line_client.py` と同一）。
- **例外を握って絶対に無反応にしない**: 取得・読み取り失敗時は必ずユーザーへ定型文を返す（`summarize.py` / `hermes_brain.py` のフォールバック思想と同じ）。
- **Hermesにファイルを渡さない**: 渡すのは常に読み取り済みテキストのみ。
- スコープ: message type `image` と `file`(PDFのみ)。`audio` は未対応（将来STT、Mac mini後）。PDF以外のファイル(docx/xlsx等)は「まだ読めない」定型文で丁寧に断る。
- 既存テストを壊さない（現在全66件green）。新規テストはTDDで先に書く。

---

## File Structure

- `interactive/line_media.py`（新規）— LINE content APIからメディア本体(bytes)とContent-Typeを取得。責務: LINE側I/Oのみ。
- `interactive/vision.py`（新規）— bytes + media_type を Haiku に読ませてテキスト化。責務: Anthropic vision/document呼び出しのみ。画像は送信前にベストエフォートで縮小。
- `interactive/media_intake.py`（新規）— 取得→読解→テキスト整形→`research_async.handle`へ受け渡すオーケストレータ。責務: 型の振り分けとフォールバック分岐。
- `interactive/server.py`（改修）— webhookループで image/file を検出し `media_intake.handle` へspawn。責務: ルーティングのみ。
- テスト: `tests/test_line_media.py` / `tests/test_vision.py` / `tests/test_media_intake.py`（新規）、`tests/test_server.py`（追記）。

---

## Task 1: LINE content 取得 (`line_media.py`)

**Files:**
- Create: `interactive/line_media.py`
- Test: `tests/test_line_media.py`

**Interfaces:**
- Produces: `fetch_content(message_id: str, *, token: str | None = None, timeout: int = 30) -> tuple[bytes, str]` — 戻り値 `(data, content_type)`。`content_type` は小文字・パラメータ除去済み（例 `"image/jpeg"`, `"application/pdf"`）。取得失敗時は例外を送出（呼び出し側 `media_intake` が握る）。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_line_media.py
"""LINE content API(メディア本体取得)のテスト。"""
import interactive.line_media as line_media


class _Resp:
    def __init__(self, content, ctype, status=200):
        self.content = content
        self.headers = {"Content-Type": ctype}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_content_hits_data_endpoint_with_auth(monkeypatch):
    seen = {}

    def _get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        return _Resp(b"\xff\xd8jpegbytes", "image/jpeg; charset=binary")

    monkeypatch.setattr(line_media.requests, "get", _get)
    data, ctype = line_media.fetch_content("MID123", token="TKN")

    assert data == b"\xff\xd8jpegbytes"
    assert ctype == "image/jpeg"                       # パラメータ除去・小文字化
    assert seen["url"] == "https://api-data.line.me/v2/bot/message/MID123/content"
    assert seen["headers"]["Authorization"] == "Bearer TKN"


def test_fetch_content_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(line_media.requests, "get",
                        lambda url, headers=None, timeout=None: _Resp(b"", "text/html", status=404))
    try:
        line_media.fetch_content("MID", token="TKN")
        assert False, "例外が出るべき"
    except Exception:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/yuta/line/line-news-bot && ./venv/bin/python3 -m pytest tests/test_line_media.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'interactive.line_media'`

- [ ] **Step 3: Write minimal implementation**

```python
# interactive/line_media.py
#!/usr/bin/env python3
"""LINE Messaging APIからメディア本体(画像/ファイル)を取得する薄い層。

人間→ボットのメディアは message.id で `api-data.line.me` から本体を落とせる。
認証は push/reply と同じ LINE_ACCESS_TOKEN。取得失敗は呼び出し側(media_intake)が
握ってユーザーへ定型文を返すため、ここでは素直に例外を投げる。
"""
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_ENDPOINT = "https://api-data.line.me/v2/bot/message/{mid}/content"


def fetch_content(message_id, *, token=None, timeout=30):
    """(bytes, content_type) を返す。content_type は小文字・パラメータ除去済み。"""
    token = token or os.environ.get("LINE_ACCESS_TOKEN", "")
    r = requests.get(
        _ENDPOINT.format(mid=message_id),
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    r.raise_for_status()
    ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    return r.content, ctype
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/yuta/line/line-news-bot && ./venv/bin/python3 -m pytest tests/test_line_media.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/yuta/line/line-news-bot
git add interactive/line_media.py tests/test_line_media.py
git commit -m "feat(capture): LINE content APIでメディア本体を取得するline_mediaを追加"
```

---

## Task 2: Haiku 読解 (`vision.py`)

**Files:**
- Create: `interactive/vision.py`
- Test: `tests/test_vision.py`

**Interfaces:**
- Consumes: `(data, media_type)` — media_typeは `line_media.fetch_content` のcontent_type（`"image/jpeg"` 等 or `"application/pdf"`）。
- Produces: `read(data: bytes, media_type: str, *, timeout: int = 60) -> str` — Haikuが読み取った日本語テキスト。鍵未設定・空データ・非対応media_type・API失敗のいずれでも `""` を返す（例外を出さない）。

補足: 画像は送信前に Pillow でベストエフォート縮小（Anthropic推奨の最長辺1568px、リクエスト肥大とコストを抑える）。Pillow未導入や縮小失敗時は原本をそのまま送る。

- [ ] **Step 1: Install Pillow into the venv（縮小のため。無くても動くが入れておく）**

Run: `cd /home/yuta/line/line-news-bot && ./venv/bin/python3 -m pip install Pillow`
Expected: `Successfully installed Pillow-...`（既に入っていれば "already satisfied"）

- [ ] **Step 2: Write the failing test**

```python
# tests/test_vision.py
"""vision.read(画像/PDFをHaikuでテキスト化)のテスト。API本体はモックする。"""
import base64
import interactive.vision as vision


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _patch_post(monkeypatch, capture):
    def _post(url, headers=None, json=None, timeout=None):
        capture["url"] = url
        capture["headers"] = headers
        capture["json"] = json
        return _Resp({"content": [{"type": "text", "text": "領収書 3200円 5/1"}]})
    monkeypatch.setattr(vision.requests, "post", _post)


def test_read_image_sends_image_block_and_returns_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cap = {}
    _patch_post(monkeypatch, cap)
    out = vision.read(b"\xff\xd8rawjpeg", "image/jpeg")

    assert out == "領収書 3200円 5/1"
    assert cap["json"]["model"] == "claude-haiku-4-5"
    blocks = cap["json"]["messages"][0]["content"]
    kinds = [b["type"] for b in blocks]
    assert "image" in kinds                    # 画像ブロックが入る
    img = next(b for b in blocks if b["type"] == "image")
    assert img["source"]["type"] == "base64"
    assert img["source"]["media_type"].startswith("image/")
    # dataは正しくbase64（デコードできる）
    base64.b64decode(img["source"]["data"])


def test_read_pdf_sends_document_block(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cap = {}
    _patch_post(monkeypatch, cap)
    out = vision.read(b"%PDF-1.4 fake", "application/pdf")

    assert out == "領収書 3200円 5/1"
    blocks = cap["json"]["messages"][0]["content"]
    doc = next(b for b in blocks if b["type"] == "document")
    assert doc["source"]["media_type"] == "application/pdf"


def test_read_unsupported_media_type_returns_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # postが呼ばれたら失敗させる（呼ばれないことの確認）
    monkeypatch.setattr(vision.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("呼ぶな")))
    assert vision.read(b"data", "application/vnd.ms-excel") == ""


def test_read_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert vision.read(b"data", "image/jpeg") == ""


def test_read_api_error_returns_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(vision.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert vision.read(b"data", "image/jpeg") == ""
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /home/yuta/line/line-news-bot && ./venv/bin/python3 -m pytest tests/test_vision.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'interactive.vision'`

- [ ] **Step 4: Write minimal implementation**

```python
# interactive/vision.py
#!/usr/bin/env python3
"""画像/PDFをHaiku(vision/document)で日本語テキストに読み取る層。

Hermesはファイルを扱えない/扱わせない方針なので、メディアはここで「テキスト」に
変換してから渡す。summarize.py と同じAnthropicのMessages API直叩き・同じ鍵束。
出力は「忠実な読み取り」に徹し、整理・判断は後段(Hermes)に任せる。
失敗しても例外を出さず "" を返す(呼び出し側が定型文でフォロー)。
"""
import base64
import os
from io import BytesIO
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path.home() / ".hermes" / ".env")

_MODEL = "claude-haiku-4-5"
_ENDPOINT = "https://api.anthropic.com/v1/messages"
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_MAX_EDGE = 1568  # Anthropic推奨の最長辺

_PROMPT = (
    "この画像/PDFに写っている情報を、日本語で忠実に読み取ってください。\n"
    "・本文テキストは省略せず書き出す（金額・日付・番号・固有名詞を正確に）。\n"
    "・表や図、写真の要素は簡潔に描写する。\n"
    "・要約や意見・前置きは加えず、読み取れた情報だけを出力する。"
)


def _prepare_image(data, media_type):
    """画像を最長辺1568pxへ縮小しJPEG化(ベストエフォート)。失敗時は原本を返す。"""
    try:
        from PIL import Image
        im = Image.open(BytesIO(data)).convert("RGB")
        im.thumbnail((_MAX_EDGE, _MAX_EDGE))
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:
        print(f"[WARN] vision downscale skipped: {e}")
        return data, media_type


def read(data, media_type, *, timeout=60):
    """画像/PDFをHaikuで読み取り日本語テキストで返す。失敗時は ""(例外を出さない)。"""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or not data:
        return ""

    if media_type == "application/pdf":
        block = {"type": "document", "source": {
            "type": "base64", "media_type": "application/pdf",
            "data": base64.b64encode(data).decode(),
        }}
    elif media_type in _IMAGE_TYPES:
        data, media_type = _prepare_image(data, media_type)
        block = {"type": "image", "source": {
            "type": "base64", "media_type": media_type,
            "data": base64.b64encode(data).decode(),
        }}
    else:
        return ""  # 非対応(docx/xlsx/audio等)

    try:
        r = requests.post(
            _ENDPOINT,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _MODEL,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": [block, {"type": "text", "text": _PROMPT}]}],
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data_json = r.json()
        out = "".join(
            b.get("text", "") for b in data_json.get("content", []) if b.get("type") == "text"
        ).strip()
        return out
    except Exception as e:
        print(f"[ERROR] vision.read: {e}")
        return ""
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/yuta/line/line-news-bot && ./venv/bin/python3 -m pytest tests/test_vision.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
cd /home/yuta/line/line-news-bot
git add interactive/vision.py tests/test_vision.py
git commit -m "feat(capture): 画像/PDFをHaikuで読み取るvisionを追加(画像は自動縮小)"
```

---

## Task 3: 取り込みオーケストレータ (`media_intake.py`)

**Files:**
- Create: `interactive/media_intake.py`
- Test: `tests/test_media_intake.py`

**Interfaces:**
- Consumes: `line_media.fetch_content`(Task1), `vision.read`(Task2), `research_async.handle(text, reply_token, session_id)`(既存), `line_client.reply(reply_token, text)`(既存)。
- Produces: `handle(message_id: str, kind: str, reply_token: str, *, session_id="line-owner", fetch=..., read=..., route=..., reply=...) -> str` — 戻り値は経路文字列 `"handled" | "unsupported" | "read_error" | "fetch_error"`。`kind` は `"image"` か `"file"`（LINE message type）。読み取れたら整形テキストを `route`(=research_async.handle)へ渡し、Hermes経由でLINEに返す。読めなければ `reply` で定型文を返す。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_media_intake.py
"""media_intake.handle(取得→読解→Hermesへ受け渡し)のテスト。全依存をinjectする。"""
import interactive.media_intake as mi


def _mk(**over):
    calls = {"routed": [], "replied": []}

    def fetch(mid): return over.get("fetch_ret", (b"bytes", "image/jpeg"))
    def read(data, mtype): return over.get("read_ret", "領収書 3200円 5/1")
    def route(text, rt, sid): calls["routed"].append((text, rt, sid))
    def reply(rt, text): calls["replied"].append((rt, text))

    if over.get("fetch_raises"):
        def fetch(mid): raise RuntimeError("net down")  # noqa: E306,E704

    return calls, dict(fetch=fetch, read=read, route=route, reply=reply)


def test_image_extraction_is_routed_to_hermes_as_text():
    calls, dep = _mk()
    r = mi.handle("MID", "image", "RT", **dep)
    assert r == "handled"
    assert calls["replied"] == []                 # 直接replyせずHermes経由
    assert len(calls["routed"]) == 1
    text, rt, sid = calls["routed"][0]
    assert rt == "RT" and sid == "line-owner"
    assert "領収書 3200円 5/1" in text             # 読み取り結果が本文に入る
    assert "画像" in text                          # 画像由来と分かる前置き


def test_pdf_file_is_supported():
    calls, dep = _mk(fetch_ret=(b"%PDF", "application/pdf"), read_ret="請求書 合計 12,000円")
    r = mi.handle("MID", "file", "RT", **dep)
    assert r == "handled"
    text, _, _ = calls["routed"][0]
    assert "請求書 合計 12,000円" in text


def test_unsupported_file_type_replies_politely():
    calls, dep = _mk(fetch_ret=(b"xlsxdata", "application/vnd.ms-excel"))
    r = mi.handle("MID", "file", "RT", **dep)
    assert r == "unsupported"
    assert calls["routed"] == []                   # Hermesへ渡さない
    assert len(calls["replied"]) == 1
    assert "読め" in calls["replied"][0][1]         # 「まだ読めない」旨


def test_empty_extraction_replies_failure():
    calls, dep = _mk(read_ret="")
    r = mi.handle("MID", "image", "RT", **dep)
    assert r == "read_error"
    assert calls["routed"] == []
    assert len(calls["replied"]) == 1


def test_fetch_failure_replies_failure():
    calls, dep = _mk(fetch_raises=True)
    r = mi.handle("MID", "image", "RT", **dep)
    assert r == "fetch_error"
    assert calls["routed"] == []
    assert len(calls["replied"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/yuta/line/line-news-bot && ./venv/bin/python3 -m pytest tests/test_media_intake.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'interactive.media_intake'`

- [ ] **Step 3: Write minimal implementation**

```python
# interactive/media_intake.py
#!/usr/bin/env python3
"""LINEに来た画像/PDFを「テキスト」に変換してHermesへ渡すオーケストレータ。

流れ: LINE content取得(line_media) → Haiku読解(vision) → 前置きを付けて
既存の自己昇格ディスパッチャ(research_async.handle)へ。Hermesは読み取り済み
テキストだけを受け取り、整理してLINEへ返す(ファイルは一切触らせない)。
取得/読解に失敗したら、無反応にせず定型文をユーザーへ返す。
"""
from interactive import line_media
from interactive import research_async
from shared import line_client

_UNSUPPORTED = "ごめん、その形式のファイルはまだ読めないんだ。写真かPDFなら読めるよ！"
_READ_FAIL = "うまく読み取れなかった…もう一度送ってみてくれる?"
_FETCH_FAIL = "ファイルの取得でつまずいちゃった。もう一度送ってみて。"

# LINE content-type → 対応可否。file(PDF)と各画像のみ通す。
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _normalize(content_type):
    """対応するmedia_typeを返す。非対応なら None。"""
    if content_type in _IMAGE_TYPES:
        return content_type
    if content_type == "application/pdf":
        return "application/pdf"
    return None


def _wrap(media_type, extraction):
    """読み取りテキストに、Hermesへの前置き指示を付ける。"""
    what = "PDF" if media_type == "application/pdf" else "画像"
    return (
        f"[オーナーが{what}を共有しました]\n"
        f"以下はその{what}から読み取った内容です"
        "（あなたに現物は見えていません。この読み取り結果だけで応答してください）:\n"
        "---\n"
        f"{extraction}\n"
        "---\n"
        "内容を日本語で簡潔に整理して伝えてください。日付・金額・締切・タスクなど"
        "後で役立つ情報があれば拾ってください。特に指示がなければ要点整理だけでよく、"
        "その場合はweb検索などのツールは使わないでください。"
    )


def handle(message_id, kind, reply_token, *, session_id="line-owner",
           fetch=line_media.fetch_content, read=vision_read,
           route=research_async.handle, reply=line_client.reply):
    """画像/PDFを取り込みHermes経由でLINEへ返す。戻り値=経路文字列。"""
    try:
        data, content_type = fetch(message_id)
    except Exception as e:
        print(f"[ERROR] media_intake fetch: {e}")
        reply(reply_token, _FETCH_FAIL)
        return "fetch_error"

    media_type = _normalize(content_type)
    if media_type is None:
        reply(reply_token, _UNSUPPORTED)
        return "unsupported"

    extraction = read(data, media_type)
    if not extraction:
        reply(reply_token, _READ_FAIL)
        return "read_error"

    route(_wrap(media_type, extraction), reply_token, session_id)
    return "handled"
```

**注意（実装時に必ず直す）:** 上の `read=vision_read` はプレースホルダ表記。実ファイルでは冒頭 import に `from interactive.vision import read as vision_read` を追加し、デフォルト引数 `read=vision_read` がそれを指すようにすること（`vision.read` という名前は `route`/`reply` と同じくデフォルト差し替え可能にするため関数参照で束縛する）。具体的には import 群を次にする:

```python
from interactive import line_media
from interactive import research_async
from interactive.vision import read as vision_read
from shared import line_client
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/yuta/line/line-news-bot && ./venv/bin/python3 -m pytest tests/test_media_intake.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/yuta/line/line-news-bot
git add interactive/media_intake.py tests/test_media_intake.py
git commit -m "feat(capture): 画像/PDFをテキスト化してHermesへ渡すmedia_intakeを追加"
```

---

## Task 4: webhook で image/file を振り分け (`server.py`)

**Files:**
- Modify: `interactive/server.py:17-20`（import追加）, `interactive/server.py:116-129`（webhookループ）
- Test: `tests/test_server.py`（追記）

**Interfaces:**
- Consumes: `media_intake.handle(message_id, kind, reply_token)`(Task3)。
- Produces: 既存の `/webhook` が message type `image`/`file` を受けたら `media_intake.handle` をバックグラウンドspawnする。`text` は従来通り。`audio` 等は従来通りスキップ。

- [ ] **Step 1: Write the failing test（test_server.py の末尾に追記）**

```python
# tests/test_server.py に追記

def _setup_media(monkeypatch, calls):
    """署名OK・同期spawn・media_intake.handleを記録するスタブ。"""
    monkeypatch.setattr(server, "CHANNEL_SECRET", SECRET)
    monkeypatch.setattr(server, "verify_signature", lambda b, s: True)
    monkeypatch.setattr(server, "_spawn", lambda fn: fn())
    monkeypatch.setattr(server.media_intake, "handle",
                        lambda mid, kind, rt: calls.append((mid, kind, rt)))
    server._seen_ids.clear()
    server._seen_set.clear()


def _media_event(mtype="image", mid="M1", event_id="E9", reply_token="RT",
                 file_name=None):
    msg = {"type": mtype, "id": mid}
    if file_name:
        msg["fileName"] = file_name
    return {"type": "message", "replyToken": reply_token, "webhookEventId": event_id,
            "deliveryContext": {"isRedelivery": False}, "message": msg}


def test_webhook_routes_image_to_media_intake(monkeypatch):
    calls = []
    _setup_media(monkeypatch, calls)
    r = _post(server.app.test_client(), [_media_event(mtype="image", mid="IMG1")])
    assert r.status_code == 200
    assert calls == [("IMG1", "image", "RT")]


def test_webhook_routes_file_to_media_intake(monkeypatch):
    calls = []
    _setup_media(monkeypatch, calls)
    r = _post(server.app.test_client(),
              [_media_event(mtype="file", mid="F1", file_name="請求書.pdf")])
    assert r.status_code == 200
    assert calls == [("F1", "file", "RT")]


def test_webhook_ignores_audio(monkeypatch):
    calls = []
    _setup_media(monkeypatch, calls)
    r = _post(server.app.test_client(), [_media_event(mtype="audio", mid="A1")])
    assert r.status_code == 200
    assert calls == []                         # 音声は未対応(スコープ外)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/yuta/line/line-news-bot && ./venv/bin/python3 -m pytest tests/test_server.py -v -k media`
Expected: FAIL — `AttributeError: module 'interactive.server' has no attribute 'media_intake'`

- [ ] **Step 3: Add the import**

`interactive/server.py` の import 群（17-20行目付近）に1行追加:

```python
from interactive import dispatch
from interactive import hermes_brain
from interactive import media_intake      # ← 追加
from interactive import research_async
from shared import line_client
```

- [ ] **Step 4: Rewrite the webhook loop**

`interactive/server.py` の webhook ループ本体（現116-129行）を次に差し替える:

```python
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
```

- [ ] **Step 5: Run the new tests and the full suite**

Run: `cd /home/yuta/line/line-news-bot && ./venv/bin/python3 -m pytest tests/test_server.py -v`
Expected: PASS（既存4件 + 新規3件）

Run: `cd /home/yuta/line/line-news-bot && ./venv/bin/python3 -m pytest -q`
Expected: PASS（既存66件 + 新規15件 = 全81件green。回帰なし）

- [ ] **Step 6: Commit**

```bash
cd /home/yuta/line/line-news-bot
git add interactive/server.py tests/test_server.py
git commit -m "feat(capture): LINE webhookで画像/PDFをmedia_intakeへ振り分け"
```

---

## Task 5: 実機疎通確認（手動・任意だが強く推奨）

**Files:** なし（稼働確認のみ）

- [ ] **Step 1: サービス再起動**

```bash
systemctl --user restart secretary-webhook
systemctl --user status secretary-webhook --no-pager | head -5
```
Expected: `active (running)`

- [ ] **Step 2: ANTHROPIC_API_KEY が読めているか確認**

```bash
cd /home/yuta/line/line-news-bot && ./venv/bin/python3 -c "import os; from pathlib import Path; from dotenv import load_dotenv; load_dotenv(Path.home()/'.hermes'/'.env'); print('key set:', bool(os.environ.get('ANTHROPIC_API_KEY')))"
```
Expected: `key set: True`

- [ ] **Step 3: LINEで写真を1枚共有 → 要点整理が返ることを確認**

LINEトークに写真（レシート/書類など文字のあるもの推奨）を送る。数秒〜数十秒でHermesが要点整理を返せばOK。返らない場合は `journalctl --user -u secretary-webhook -n 50 --no-pager` でエラーを確認（`[ERROR] vision.read` / `media_intake fetch` を見る）。

- [ ] **Step 4: PDFを共有 → 読解が返ることを確認**

LINEトークにPDFファイルを送る（共有→LINE）。同様に要点が返ればOK。

- [ ] **Step 5: 非対応ファイル（例: .xlsx）→「まだ読めない」返答を確認**

Expected: `ごめん、その形式のファイルはまだ読めないんだ。写真かPDFなら読めるよ！`

---

## Self-Review

**Spec coverage（記憶 project_hermes_capture.md ロードマップ#1「写真/PDFの共有→LINE入力を開通」）:**
- 写真入力 → Task1(取得)+Task2(vision画像)+Task3+Task4 ✅
- PDF入力 → Task2(document)+Task3(_normalize)+Task4 ✅
- Haikuネイティブ読解・STT不要 → Task2 ✅
- Hermesにファイル権限を与えない（テキストで渡す） → Task3 `_wrap`→`research_async.handle` ✅
- 音声はスコープ外（Mac mini後） → Task4で `audio` を明示スキップ ✅
- 無反応にしない → Task3の全失敗分岐でreply ✅

**Placeholder scan:** Task3の `read=vision_read` は「注意」節で実importを明示（意図的な明示、放置プレースホルダではない）。他にTBD/TODO無し。

**Type consistency:** `fetch_content -> (bytes, str)` / `vision.read(bytes, str) -> str` / `media_intake.handle(str,str,str) -> str` / `research_async.handle(text, reply_token, session_id)` は既存シグネチャと一致。`_normalize` の対応集合 `_IMAGE_TYPES` は vision.py と media_intake.py で同一値。webhook が渡す `kind`（"image"/"file"）は media_intake が受ける `kind` と一致。

---

## Notes / 既知のリスク（実装者向け）

- **PDFのbeta header**: Haiku 4.5 ではPDFはGA想定のため `anthropic-beta` は付けていない。もしPDFで 400(document未対応) が返る場合は、vision.py のPDF分岐リクエストに `"anthropic-beta": "pdfs-2024-09-25"` ヘッダを足す。
- **画像サイズ**: Pillow縮小で最長辺1568pxに落とすため通常はAnthropicの上限内。Pillow未導入時は原本送信となり、巨大写真(>5MB)でAPIが400を返し得る→その場合 `read` は "" を返し `_READ_FAIL` でユーザーに伝わる（無反応にはならない）。恒久対策はPillow導入(Task2 Step1)。
- **reply_token 期限**: vision読解は数秒かかるが、`line_client.reply` は失敗時 `push` へ自動フォールバックするため、万一token失効しても返信は届く。
- **HERMES_BRAIN=off の場合**: media_intake は `research_async.handle`（Hermes経路）を直接呼ぶため、`HERMES_BRAIN` スイッチに関係なく画像/PDFは常にHermesで処理される。text経路の `_process` とは独立。これは意図的（画像読解はGemini経路 dispatch では未対応のため）。テスト conftest の既定 off は text経路のみに影響。
