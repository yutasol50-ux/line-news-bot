# 夜の日記（Hermes Nightly Diary） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 20時にHermesがLINEで声をかけ、会話しながら集めた一日をHaikuが忠実に清書し、ローカルに保存して「本棚Webページ」で見返せる日記機能を作る。

**Architecture:** 既存の `interactive/` 層の流儀を踏襲する。Hermesにファイル権限は与えず、LINE側ハンドラ(`diary_collector`)がテキスト化・状態管理・保存まで完結させる。Haiku呼び出しは `summarize.py`/`vision.py` と同じ Messages API 直叩き。下書き状態はファイル永続化し、サーバ再起動でも消えない。清書失敗時は原文で保存し、日記を絶対に失わない。

**Tech Stack:** Python 3, Flask(既存 `server.py`), `requests`(Anthropic Messages API 直叩き), pytest + monkeypatch/依存injection, cron(既存 `setup_cron.sh`)。

## Global Constraints

- Haikuモデルは `claude-haiku-4-5`、エンドポイント `https://api.anthropic.com/v1/messages`、ヘッダ `x-api-key` / `anthropic-version: 2023-06-01` / `content-type: application/json`。鍵は `~/.hermes/.env` の `ANTHROPIC_API_KEY`(`load_dotenv(Path.home()/".hermes"/".env")`)。
- **例外を絶対に外へ出さない**。API/ネット失敗は各モジュール内で握り、安全な値へフォールバックする(LINE無反応・データ喪失を防ぐ)。
- **清書は忠実**。誤字・話し言葉・箇条書きを読みやすく整えるだけ。出来事や気持ちを足さない。原文(`raw`)を必ず保存する。
- 日付は JST。`JST = timezone(timedelta(hours=9))`、`datetime.now(JST)`。日付文字列は `%Y-%m-%d`。
- テストは依存injection(関数引数で `classify=`/`compose=`/`store=`/`reply=` 等を差し替え可能)にし、実APIもLINEも叩かないこと。既存 `tests/conftest.py`(HERMES_BRAIN既定off)を尊重。
- 会話部屋(session)は既存と同じ `line-owner`。
- テスト実行はリポジトリ直下から `venv/bin/python -m pytest ...`。
- 全タスク完了まで既存テストの回帰ゼロ(`venv/bin/python -m pytest tests/ -q`)。

## File Structure

新規(すべて `interactive/`, 単一責務):
- `diary_store.py` — 日記エントリと写真の永続化/取得。
- `diary_compose.py` — Haiku清書(title/tags/body生成)。忠実・失敗時は原文フォールバック。
- `diary_classify.py` — 返信の意図判定(affirm/reject/more/content)。Haiku＋キーワードフォールバック。
- `diary_state.py` — 下書き状態機械(ファイル永続化)。純粋(Haikuを呼ばない)。
- `diary_collector.py` — オーケストレータ。webhookが呼ぶ入口(handle_text/handle_photo/finalize_timeout)。
- `diary_web.py` — 日記の本棚Webページ(Flask Blueprint)。

改修:
- `server.py` — webhookで日記モード中は `diary_collector` へ振り分け。`diary_web.bp` を登録。
- 新規 `diary_prompt.py`(リポジトリ直下) — 20時cron入口(時間切れ確定→声かけ→日記モード開始)。
- `setup_cron.sh` — 20:00 の cron 行を追加。
- `home-hub/services.json` — 本棚に「📔 日記」を追加。

データ配置:
- `data/diary/entries/<YYYY-MM-DD>.json` — 1日1エントリ(同日再開はマージ)。
- `data/diary/media/<YYYY-MM-DD>/<n>.jpg` — 写真本体。
- `data/diary/_active.json` — 進行中の下書き状態。

---

### Task 1: diary_store.py（永続化）

**Files:**
- Create: `interactive/diary_store.py`
- Test: `tests/test_diary_store.py`

**Interfaces:**
- Produces:
  - `DIARY_DIR: Path`(= `data/diary`。テストで monkeypatch 可能なモジュール変数)
  - `save(entry: dict) -> str` — `entries/<date>.json` に書く。同日既存があればマージ(bodyは改行区切りで連結、rawも連結、tagsは重複排除で和、photos拡張、titleは新しい方、updated更新)。戻り値=書いたファイルパス文字列。
  - `list_entries() -> list[dict]` — 全エントリを日付降順で返す。無ければ `[]`。
  - `get(date: str) -> dict | None`
  - `save_photo(date: str, data: bytes, ext: str = ".jpg") -> str` — `media/<date>/<n><ext>` に保存し**ファイル名のみ**(`"1.jpg"`)を返す。連番は既存枚数+1。
  - `media_path(date: str, filename: str) -> Path`
- entry schema: `{"date","title","tags":[...],"body","raw","photos":[{"file","caption"}],"created","updated"}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diary_store.py
"""diary_store: 日記エントリと写真の永続化。同日はマージ。"""
import json
from interactive import diary_store as ds


def _entry(date="2026-07-07", **over):
    e = {"date": date, "title": "テスト", "tags": ["疲れ"], "body": "本文",
         "raw": "げんぶん", "photos": [], "created": "t0", "updated": "t0"}
    e.update(over)
    return e


def test_save_and_get_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "DIARY_DIR", tmp_path)
    ds.save(_entry())
    got = ds.get("2026-07-07")
    assert got["body"] == "本文"
    assert got["raw"] == "げんぶん"
    assert got["tags"] == ["疲れ"]


def test_same_day_merges(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "DIARY_DIR", tmp_path)
    ds.save(_entry(body="午前の分", raw="あさ", tags=["疲れ"]))
    ds.save(_entry(body="夜の追記", raw="よる", tags=["嬉しい"], title="夜"))
    got = ds.get("2026-07-07")
    assert "午前の分" in got["body"] and "夜の追記" in got["body"]
    assert "あさ" in got["raw"] and "よる" in got["raw"]
    assert set(got["tags"]) == {"疲れ", "嬉しい"}   # 重複排除の和
    assert got["title"] == "夜"                     # 新しい方


def test_list_is_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "DIARY_DIR", tmp_path)
    ds.save(_entry(date="2026-07-05"))
    ds.save(_entry(date="2026-07-07"))
    dates = [e["date"] for e in ds.list_entries()]
    assert dates == ["2026-07-07", "2026-07-05"]


def test_save_photo_returns_filename_and_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "DIARY_DIR", tmp_path)
    f1 = ds.save_photo("2026-07-07", b"JPEGDATA")
    f2 = ds.save_photo("2026-07-07", b"JPEGDATA2")
    assert f1 == "1.jpg" and f2 == "2.jpg"
    assert ds.media_path("2026-07-07", "1.jpg").read_bytes() == b"JPEGDATA"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_diary_store.py -v`
Expected: FAIL(`ModuleNotFoundError: interactive.diary_store` / `AttributeError`)

- [ ] **Step 3: Write minimal implementation**

```python
# interactive/diary_store.py
#!/usr/bin/env python3
"""日記エントリと写真の永続化/取得。同日は1エントリにマージする。

保存先は data/diary/(テストは DIARY_DIR を monkeypatch で差し替える)。
ファイルシステムのみに依存。
"""
import json
from pathlib import Path

DIARY_DIR = Path(__file__).resolve().parent.parent / "data" / "diary"


def _entries_dir() -> Path:
    d = DIARY_DIR / "entries"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _entry_file(date: str) -> Path:
    return _entries_dir() / f"{date}.json"


def get(date: str):
    f = _entry_file(date)
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def _merge(old: dict, new: dict) -> dict:
    out = dict(old)
    out["body"] = (old.get("body", "") + "\n\n" + new.get("body", "")).strip()
    out["raw"] = (old.get("raw", "") + "\n\n" + new.get("raw", "")).strip()
    tags = list(old.get("tags", []))
    for t in new.get("tags", []):
        if t not in tags:
            tags.append(t)
    out["tags"] = tags
    out["photos"] = list(old.get("photos", [])) + list(new.get("photos", []))
    out["title"] = new.get("title") or old.get("title")
    out["updated"] = new.get("updated") or old.get("updated")
    return out


def save(entry: dict) -> str:
    date = entry["date"]
    existing = get(date)
    final = _merge(existing, entry) if existing else entry
    f = _entry_file(date)
    f.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(f)


def list_entries():
    d = _entries_dir()
    out = []
    for f in d.glob("*.json"):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"[WARN] diary_store list skip {f}: {e}")
    out.sort(key=lambda e: e.get("date", ""), reverse=True)
    return out


def media_path(date: str, filename: str) -> Path:
    return DIARY_DIR / "media" / date / filename


def save_photo(date: str, data: bytes, ext: str = ".jpg") -> str:
    d = DIARY_DIR / "media" / date
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob("*"))) + 1
    filename = f"{n}{ext}"
    (d / filename).write_bytes(data)
    return filename
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_diary_store.py -v`
Expected: PASS(4件)

- [ ] **Step 5: Commit**

```bash
git add interactive/diary_store.py tests/test_diary_store.py
git commit -m "feat(diary): エントリ/写真の永続化(同日マージ)"
```

---

### Task 2: diary_compose.py（Haiku清書）

**Files:**
- Create: `interactive/diary_compose.py`
- Test: `tests/test_diary_compose.py`

**Interfaces:**
- Consumes: Anthropic Messages API(`requests`)。
- Produces: `compose(raw: str, photo_captions: list[str] | None = None, *, date: str, timeout: int = 30) -> dict` — `{"title": str, "tags": list[str], "body": str}` を返す。Haikuに厳密JSONで出させる。失敗/空/パース不能時は `{"title": date, "tags": [], "body": raw}` にフォールバック(例外を出さない)。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diary_compose.py
"""diary_compose: Haiku清書。失敗時は原文フォールバック(例外を出さない)。"""
from interactive import diary_compose as dc


class _Resp:
    def __init__(self, text): self._t = text
    def raise_for_status(self): pass
    def json(self): return {"content": [{"type": "text", "text": self._t}]}


def test_compose_parses_haiku_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    payload = '{"title":"職場の当務","tags":["疲れ","仕事"],"body":"今日は当務だった。"}'
    monkeypatch.setattr(dc.requests, "post", lambda *a, **k: _Resp(payload))
    out = dc.compose("・当務\n・つかれた", date="2026-07-07")
    assert out["title"] == "職場の当務"
    assert out["tags"] == ["疲れ", "仕事"]
    assert "当務" in out["body"]


def test_compose_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(dc.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("叩くな")))
    out = dc.compose("・箇条書きのまま", date="2026-07-07")
    assert out["title"] == "2026-07-07"
    assert out["tags"] == []
    assert out["body"] == "・箇条書きのまま"   # 原文は失わない


def test_compose_falls_back_on_bad_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(dc.requests, "post", lambda *a, **k: _Resp("これはJSONじゃない"))
    out = dc.compose("原文テキスト", date="2026-07-07")
    assert out["body"] == "原文テキスト"       # パース不能でも原文で保存
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_diary_compose.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation**

```python
# interactive/diary_compose.py
#!/usr/bin/env python3
"""下書き(原文+写真キャプション)をHaikuで忠実に清書し、title/tags/bodyを返す。

清書は「整えるだけ・盛らない」。失敗/パース不能時は原文をそのまま body に入れて
返す(日記を絶対に失わない。summarize.py と同じ思想)。
"""
import json
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path.home() / ".hermes" / ".env")

_MODEL = "claude-haiku-4-5"
_ENDPOINT = "https://api.anthropic.com/v1/messages"
_MAX_INPUT = 12000
_PROMPT = (
    "あなたはオーナー本人の日記を整えるアシスタントです。以下の下書きを、"
    "読みやすい日本語の日記本文に清書してください。\n"
    "【厳守】誤字・話し言葉・箇条書きを自然な文章に整えるだけ。"
    "書かれていない出来事や気持ちを足さない。事実を変えない。\n"
    "次のJSONだけを出力(前後に何も書かない):\n"
    '{{"title": "その日を一言で表す短い見出し", '
    '"tags": ["気分や出来事のタグを2〜3個"], '
    '"body": "清書した日記本文"}}\n\n'
    "--- 下書き ---\n{raw}"
)


def _fallback(raw: str, date: str) -> dict:
    return {"title": date, "tags": [], "body": raw.strip()}


def _extract_json(text: str):
    """本文からJSONオブジェクトを取り出してdict化。失敗時 None。"""
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def compose(raw: str, photo_captions=None, *, date: str, timeout: int = 30) -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    body = (raw or "").strip()
    if photo_captions:
        body += "\n\n[写真の内容]\n" + "\n".join(f"- {c}" for c in photo_captions if c)
    if not key or not body:
        return _fallback(raw, date)
    try:
        r = requests.post(
            _ENDPOINT,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": _MODEL, "max_tokens": 1024,
                  "messages": [{"role": "user",
                                "content": _PROMPT.format(raw=body[:_MAX_INPUT])}]},
            timeout=timeout,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", [])
                       if b.get("type") == "text").strip()
        obj = _extract_json(text)
        if not obj or "body" not in obj:
            return _fallback(raw, date)
        return {"title": (obj.get("title") or date).strip(),
                "tags": [str(t) for t in obj.get("tags", [])][:5],
                "body": str(obj["body"]).strip() or raw.strip()}
    except Exception as e:
        print(f"[ERROR] diary_compose: {e}")
        return _fallback(raw, date)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_diary_compose.py -v`
Expected: PASS(3件)

- [ ] **Step 5: Commit**

```bash
git add interactive/diary_compose.py tests/test_diary_compose.py
git commit -m "feat(diary): Haikuで忠実に清書(失敗時は原文フォールバック)"
```

---

### Task 3: diary_classify.py（返信の意図判定）

**Files:**
- Create: `interactive/diary_classify.py`
- Test: `tests/test_diary_classify.py`

**Interfaces:**
- Produces: `classify(text: str, *, timeout: int = 15) -> str` — 戻り値は `"affirm" | "reject" | "more" | "content"` のいずれか。
  - `affirm`=「これでいい?」への肯定(いいよ/ok/おけ/終わり/とりあえず 等、意味で判定)。
  - `reject`=やり直し/否定(ちがう/直して)。
  - `more`=まだ書き続けたいが新しい中身は無い(まだ/ちょっと待って)。
  - `content`=新しい日記の中身。
  - API失敗時は**キーワード簡易判定**へフォールバックし、それも当たらなければ `content`(=中身として貯める。取りこぼさない)。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diary_classify.py
"""diary_classify: 返信の意図(affirm/reject/more/content)。API失敗はキーワードで凌ぐ。"""
from interactive import diary_classify as dcl


class _Resp:
    def __init__(self, label): self._l = label
    def raise_for_status(self): pass
    def json(self): return {"content": [{"type": "text", "text": self._l}]}


def test_haiku_label_is_used(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(dcl.requests, "post", lambda *a, **k: _Resp("affirm"))
    assert dcl.classify("うん、それでいいよ") == "affirm"


def test_keyword_fallback_affirm_on_api_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(dcl.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert dcl.classify("おけ") == "affirm"
    assert dcl.classify("終わり！") == "affirm"


def test_keyword_fallback_content_default(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(dcl.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    # 中身っぽい文はフォールバックでも content(取りこぼさない)
    assert dcl.classify("今日は駅で人身事故対応でバタバタした") == "content"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_diary_classify.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation**

```python
# interactive/diary_classify.py
#!/usr/bin/env python3
"""日記モード中の返信を affirm/reject/more/content に分類する。

「これでいい?」への肯定なら何でも確定スイッチにする(キーワード一致でなく意味で判定)。
API失敗時は簡易キーワード、それも外れれば content(=中身として貯め、取りこぼさない)。
"""
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path.home() / ".hermes" / ".env")

_MODEL = "claude-haiku-4-5"
_ENDPOINT = "https://api.anthropic.com/v1/messages"
_LABELS = ("affirm", "reject", "more", "content")
_PROMPT = (
    "日記アプリで「これでいい?」と聞いた直後のユーザー返信を分類します。\n"
    "次の1語だけを出力(説明禁止):\n"
    "affirm = 肯定・OK・書き終わり(いいよ/ok/おけ/おk/終わり/とりあえず 等)\n"
    "reject = 否定・やり直したい(ちがう/直して 等)\n"
    "more = まだ書き足したいが新しい内容は無い(まだ/ちょっと待って 等)\n"
    "content = 新しい日記の中身(出来事・気持ちなど)\n\n"
    "返信: {text}"
)

_AFFIRM_WORDS = ("いいよ", "いい", "ok", "ｏｋ", "おけ", "おk", "終わり", "おわり",
                 "とりあえず", "だいじょうぶ", "大丈夫", "うん", "はい")
_REJECT_WORDS = ("ちがう", "違う", "直し", "やり直", "だめ", "ダメ")
_MORE_WORDS = ("まだ", "ちょっと待", "待って")


def _keyword(text: str) -> str:
    t = text.strip().lower()
    if len(t) <= 12:  # 短い返事だけ制御語とみなす(長文は中身)
        if any(w in t for w in _REJECT_WORDS):
            return "reject"
        if any(w in t for w in _MORE_WORDS):
            return "more"
        if any(w in t for w in _AFFIRM_WORDS):
            return "affirm"
    return "content"


def classify(text: str, *, timeout: int = 15) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    body = (text or "").strip()
    if not body:
        return "more"
    if not key:
        return _keyword(body)
    try:
        r = requests.post(
            _ENDPOINT,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": _MODEL, "max_tokens": 8,
                  "messages": [{"role": "user",
                                "content": _PROMPT.format(text=body[:2000])}]},
            timeout=timeout,
        )
        r.raise_for_status()
        out = "".join(b.get("text", "") for b in r.json().get("content", [])
                      if b.get("type") == "text").strip().lower()
        for label in _LABELS:
            if label in out:
                return label
        return _keyword(body)
    except Exception as e:
        print(f"[ERROR] diary_classify: {e}")
        return _keyword(body)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_diary_classify.py -v`
Expected: PASS(3件)

- [ ] **Step 5: Commit**

```bash
git add interactive/diary_classify.py tests/test_diary_classify.py
git commit -m "feat(diary): 返信の意図判定(肯定スイッチ+キーワードフォールバック)"
```

---

### Task 4: diary_state.py（下書き状態機械・ファイル永続化）

**Files:**
- Create: `interactive/diary_state.py`
- Test: `tests/test_diary_state.py`

**Interfaces:**
- Produces(状態は `STATE_FILE`= `data/diary/_active.json` に永続化。テストで monkeypatch):
  - `STATE_FILE: Path`
  - `start(date: str, *, now: str) -> None` — active化・phase="collecting"・下書きリセット。
  - `is_active() -> bool`
  - `phase() -> str`(`"collecting"` | `"confirming"`)
  - `date() -> str | None`
  - `append_text(text: str, *, now: str) -> None`
  - `append_photo(file: str, caption: str, *, now: str) -> None`
  - `raw() -> str` — 貯めたテキストを改行連結。
  - `captions() -> list[str]`
  - `photos() -> list[dict]` — `[{"file","caption"}]`
  - `set_confirming(composed: dict, *, now: str) -> None` — phase="confirming"・清書結果を保持。
  - `composed() -> dict | None`
  - `last() -> str | None` — 最終更新iso。
  - `clear() -> None` — active=False(下書き破棄)。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diary_state.py
"""diary_state: 下書き状態機械。ファイル永続化でサーバ再起動でも消えない。"""
from interactive import diary_state as st


def test_start_and_accumulate(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "_active.json")
    assert st.is_active() is False
    st.start("2026-07-07", now="t0")
    assert st.is_active() and st.phase() == "collecting" and st.date() == "2026-07-07"
    st.append_text("箇条書き1", now="t1")
    st.append_text("箇条書き2", now="t2")
    assert st.raw() == "箇条書き1\n箇条書き2"
    assert st.last() == "t2"


def test_photos_and_captions(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "_active.json")
    st.start("2026-07-07", now="t0")
    st.append_photo("1.jpg", "秩父鉄道の電車", now="t1")
    assert st.photos() == [{"file": "1.jpg", "caption": "秩父鉄道の電車"}]
    assert st.captions() == ["秩父鉄道の電車"]


def test_confirming_and_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "_active.json")
    st.start("2026-07-07", now="t0")
    st.set_confirming({"title": "x", "tags": [], "body": "b"}, now="t1")
    assert st.phase() == "confirming"
    assert st.composed()["body"] == "b"
    st.clear()
    assert st.is_active() is False


def test_state_persists_across_reload(tmp_path, monkeypatch):
    f = tmp_path / "_active.json"
    monkeypatch.setattr(st, "STATE_FILE", f)
    st.start("2026-07-07", now="t0")
    st.append_text("消えないで", now="t1")
    # 別プロセス相当: ファイルから読み直す(モジュール内キャッシュを使わない)
    assert st.is_active() and st.raw() == "消えないで"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_diary_state.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation**

```python
# interactive/diary_state.py
#!/usr/bin/env python3
"""日記モードの下書き状態機械。毎回ファイルから読み書きし、サーバ再起動でも消えない。

状態は単一JSON(_active.json)。純粋(Haiku/LINEを呼ばない)。
"""
import json
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "diary" / "_active.json"


def _load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"active": False}


def _save(s: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def start(date: str, *, now: str) -> None:
    _save({"active": True, "phase": "collecting", "date": date,
           "raw_parts": [], "photos": [], "composed": None,
           "started": now, "last": now})


def is_active() -> bool:
    return bool(_load().get("active"))


def phase() -> str:
    return _load().get("phase", "collecting")


def date():
    return _load().get("date")


def append_text(text: str, *, now: str) -> None:
    s = _load()
    s.setdefault("raw_parts", []).append(text)
    s["last"] = now
    _save(s)


def append_photo(file: str, caption: str, *, now: str) -> None:
    s = _load()
    s.setdefault("photos", []).append({"file": file, "caption": caption})
    s["last"] = now
    _save(s)


def raw() -> str:
    return "\n".join(_load().get("raw_parts", []))


def captions():
    return [p.get("caption", "") for p in _load().get("photos", [])]


def photos():
    return list(_load().get("photos", []))


def set_confirming(composed: dict, *, now: str) -> None:
    s = _load()
    s["phase"] = "confirming"
    s["composed"] = composed
    s["last"] = now
    _save(s)


def composed():
    return _load().get("composed")


def last():
    return _load().get("last")


def clear() -> None:
    _save({"active": False})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_diary_state.py -v`
Expected: PASS(4件)

- [ ] **Step 5: Commit**

```bash
git add interactive/diary_state.py tests/test_diary_state.py
git commit -m "feat(diary): 下書き状態機械(ファイル永続化)"
```

---

### Task 5: diary_collector.py（オーケストレータ）

**Files:**
- Create: `interactive/diary_collector.py`
- Test: `tests/test_diary_collector.py`

**Interfaces:**
- Consumes: `diary_state`(Task4), `diary_classify.classify`(Task3), `diary_compose.compose`(Task2), `diary_store`(Task1), `line_media.fetch_content`, `vision.read`, `shared.line_client.reply`。
- Produces:
  - `handle_text(text, reply_token, *, now=None, classify=..., compose=..., store=..., state=..., reply=...) -> str` — 戻り値は経路文字列(`"appended"|"confirm_shown"|"saved"|"reopened"|"nudge"`)。
  - `handle_photo(message_id, reply_token, *, now=None, fetch=..., read=..., store=..., state=..., reply=...) -> str` — (`"photo_added"|"photo_fail"`)。
  - `finalize_timeout(*, now_iso, cutoff_hour=2, compose=..., store=..., state=...) -> bool` — activeかつ最終更新が当日cutoff_hourを跨いでいれば自動清書・自動保存してTrue。判定は「last の日付 < now の日付、または now の時刻 >= cutoff_hour かつ last が別日」等の単純規則で可(下記実装参照)。
- 振る舞い(状態別):
  - `collecting` + `content` → `state.append_text` → reply「メモしたよ📔 これでいい?(まだ書く?)」→ `"appended"`。
  - `collecting` + `more` → 追記せず reply「うん、どうぞ✍️」→ `"nudge"`。
  - `collecting` + `affirm` → `compose(raw, captions, date)` → `state.set_confirming` → reply(清書本文 + 「こんな日記にしたよ📔 これでいい?」)→ `"confirm_shown"`。
  - `confirming` + `affirm` → `store.save(entry)` → `state.clear` → reply「保存したよ📔 また明日ね」→ `"saved"`。
  - `confirming` + `reject` → phaseを`collecting`へ戻す(`state.start`は使わず下書き保持のため `state`側に戻す手段が要る→ここでは `state.set_confirming` の逆として下書きは保持したまま collecting に戻す軽い関数を state に足さず、collector は `state.append_text("")` ではなく **`state` に `reopen()` を持たせる**)。→ reply「じゃあ続き書いてね。どこでも直せるよ」→ `"reopened"`。
  - `confirming` + `content`/`more` → 追記して collecting に戻す(`reopen`+`append_text`)→ `"reopened"`。

> 注: `reject`/追記のために **Task4 の `diary_state` に `reopen(*, now)` を追加**する(phaseを"collecting"に戻すだけ、下書きは保持)。Task5 の実装前にこの1関数を state に足し、`tests/test_diary_state.py` に1ケース追加すること(下記 Step 0)。

- [ ] **Step 0: Task4へ `reopen` を追記(TDD)**

`tests/test_diary_state.py` に追加:

```python
def test_reopen_keeps_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "_active.json")
    st.start("2026-07-07", now="t0")
    st.append_text("下書き", now="t1")
    st.set_confirming({"title": "x", "tags": [], "body": "b"}, now="t2")
    st.reopen(now="t3")
    assert st.phase() == "collecting"
    assert st.raw() == "下書き"          # 下書きは残る
    assert st.composed() is None
```

`interactive/diary_state.py` に追加:

```python
def reopen(*, now: str) -> None:
    s = _load()
    s["phase"] = "collecting"
    s["composed"] = None
    s["last"] = now
    _save(s)
```

Run: `venv/bin/python -m pytest tests/test_diary_state.py -v`(5件PASS)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diary_collector.py
"""diary_collector: 状態別の会話ハンドリング。全依存をinjectして実API/LINEを叩かない。"""
from interactive import diary_collector as col
from interactive import diary_state as st


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "_active.json")
    replies = []
    dep = dict(reply=lambda rt, text: replies.append(text))
    return replies, dep


def test_content_is_appended_and_asks_confirm(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-07", now="t0")
    r = col.handle_text("駅でバタバタした", "RT", now="t1",
                        classify=lambda t: "content", **dep)
    assert r == "appended"
    assert st.raw() == "駅でバタバタした"
    assert "これでいい" in replies[-1]


def test_affirm_composes_and_shows_confirm(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-07", now="t0")
    st.append_text("・当務\n・つかれた", now="t1")
    r = col.handle_text("いいよ", "RT", now="t2",
                        classify=lambda t: "affirm",
                        compose=lambda raw, caps, date: {"title": "当務", "tags": ["疲れ"],
                                                         "body": "今日は当務だった。"},
                        **dep)
    assert r == "confirm_shown"
    assert st.phase() == "confirming"
    assert "今日は当務だった。" in replies[-1] and "これでいい" in replies[-1]


def test_confirm_affirm_saves(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-07", now="t0")
    st.append_text("原文", now="t1")
    st.set_confirming({"title": "当務", "tags": ["疲れ"], "body": "本文"}, now="t2")
    saved = {}
    r = col.handle_text("おけ", "RT", now="t3",
                        classify=lambda t: "affirm",
                        store=type("S", (), {"save": staticmethod(lambda e: saved.update(e) or "path")}),
                        **dep)
    assert r == "saved"
    assert saved["body"] == "本文" and saved["raw"] == "原文" and saved["date"] == "2026-07-07"
    assert st.is_active() is False
    assert "保存した" in replies[-1]


def test_more_nudges_without_appending(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-07", now="t0")
    r = col.handle_text("まだ！", "RT", now="t1", classify=lambda t: "more", **dep)
    assert r == "nudge"
    assert st.raw() == ""          # 追記されない


def test_photo_is_captioned_and_stored(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-07", now="t0")
    fake_store = type("S", (), {"save_photo": staticmethod(lambda d, data: "1.jpg")})
    r = col.handle_photo("MID", "RT", now="t1",
                         fetch=lambda mid: (b"JPG", "image/jpeg"),
                         read=lambda data, mtype: "秩父鉄道の電車",
                         store=fake_store, **dep)
    assert r == "photo_added"
    assert st.photos() == [{"file": "1.jpg", "caption": "秩父鉄道の電車"}]


def test_finalize_timeout_saves_stale_draft(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-06", now="2026-07-06T21:00:00+09:00")
    st.append_text("寝落ち分", now="2026-07-06T21:05:00+09:00")
    saved = {}
    done = col.finalize_timeout(
        now_iso="2026-07-07T02:30:00+09:00",
        compose=lambda raw, caps, date: {"title": "t", "tags": [], "body": "清書"},
        store=type("S", (), {"save": staticmethod(lambda e: saved.update(e) or "p")}))
    assert done is True
    assert saved["date"] == "2026-07-06" and saved["raw"] == "寝落ち分"
    assert st.is_active() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_diary_collector.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation**

```python
# interactive/diary_collector.py
#!/usr/bin/env python3
"""日記モード中のLINEメッセージを捌くオーケストレータ。

webhookが呼ぶ入口。state(下書き)・classify(意図)・compose(清書)・store(保存)を束ね、
LINEへ返信する。Hermesにはファイルを一切触らせない(ここで完結)。
全経路で必ず何か返信し、無反応にしない。
"""
from datetime import datetime, timezone, timedelta

from interactive import diary_state as _state
from interactive import diary_classify
from interactive import diary_compose
from interactive import diary_store as _store
from interactive import line_media
from interactive.vision import read as _vision_read
from shared import line_client

_JST = timezone(timedelta(hours=9))

_ASK = "メモしたよ📔 これでいい?(まだ書くなら続けてね)"
_NUDGE = "うん、どうぞ✍️"
_SAVED = "保存したよ📔 また明日ね"
_REOPEN = "じゃあ続き書いてね。あとで「これでいい?」でまとめるよ"
_PHOTO_OK = "写真もらったよ📸 これでいい?(まだ書くなら続けてね)"
_PHOTO_FAIL = "写真うまく受け取れなかった…もう一回送ってくれる?"


def _now() -> str:
    return datetime.now(_JST).isoformat(timespec="seconds")


def _entry_from_composed(state, composed: dict, now: str) -> dict:
    date = state.date()
    return {"date": date, "title": composed.get("title", date),
            "tags": composed.get("tags", []), "body": composed.get("body", ""),
            "raw": state.raw(), "photos": state.photos(),
            "created": now, "updated": now}


def handle_text(text, reply_token, *, now=None, classify=diary_classify.classify,
                compose=diary_compose.compose, store=_store, state=_state,
                reply=line_client.reply) -> str:
    now = now or _now()
    label = classify(text)
    ph = state.phase()

    if ph == "confirming":
        if label == "affirm":
            entry = _entry_from_composed(state, state.composed(), now)
            store.save(entry)
            state.clear()
            reply(reply_token, _SAVED)
            return "saved"
        # reject / content / more は下書きへ戻して続行
        if label == "content":
            state.append_text(text, now=now)
        state.reopen(now=now)
        reply(reply_token, _REOPEN)
        return "reopened"

    # collecting
    if label == "affirm":
        composed = compose(state.raw(), state.captions(), state.date())
        state.set_confirming(composed, now=now)
        reply(reply_token, f"こんな日記にしたよ📔\n\n{composed['body']}\n\nこれでいい?")
        return "confirm_shown"
    if label == "more":
        reply(reply_token, _NUDGE)
        return "nudge"
    # content
    state.append_text(text, now=now)
    reply(reply_token, _ASK)
    return "appended"


def handle_photo(message_id, reply_token, *, now=None,
                 fetch=line_media.fetch_content, read=_vision_read,
                 store=_store, state=_state, reply=line_client.reply) -> str:
    now = now or _now()
    try:
        data, content_type = fetch(message_id)
    except Exception as e:
        print(f"[ERROR] diary_collector photo fetch: {e}")
        reply(reply_token, _PHOTO_FAIL)
        return "photo_fail"
    caption = ""
    try:
        caption = read(data, content_type) or ""
    except Exception as e:
        print(f"[WARN] diary_collector caption: {e}")
    filename = store.save_photo(state.date(), data)
    state.append_photo(filename, caption, now=now)
    reply(reply_token, _PHOTO_OK)
    return "photo_added"


def finalize_timeout(*, now_iso, cutoff_hour=2, compose=diary_compose.compose,
                     store=_store, state=_state) -> bool:
    """activeな下書きが「別日 or 当日cutoff_hour超え」なら自動清書・自動保存。"""
    if not state.is_active():
        return False
    last = state.last() or ""
    now_date = now_iso[:10]
    entry_date = state.date() or now_date
    now_hour = int(now_iso[11:13]) if len(now_iso) >= 13 else 0
    stale = (entry_date < now_date) or (last[:10] < now_date and now_hour >= cutoff_hour)
    if not stale:
        return False
    composed = compose(state.raw(), state.captions(), entry_date)
    entry = _entry_from_composed(state, composed, now_iso)
    store.save(entry)
    state.clear()
    print(f"[INFO] diary finalize_timeout saved {entry_date}")
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_diary_collector.py tests/test_diary_state.py -v`
Expected: PASS(collector 6件 + state 5件)

- [ ] **Step 5: Commit**

```bash
git add interactive/diary_collector.py interactive/diary_state.py tests/test_diary_collector.py tests/test_diary_state.py
git commit -m "feat(diary): 会話オーケストレータ(収集/確認/保存/時間切れ)"
```

---

### Task 6: server.py webhook 分岐（日記モード振り分け）

**Files:**
- Modify: `interactive/server.py`(webhook内、`for event` ループの処理部)
- Test: `tests/test_server_diary.py`

**Interfaces:**
- Consumes: `diary_collector.handle_text` / `handle_photo`, `diary_state.is_active`。
- 変更点: webhookで `reply_token` 決定後、通常処理の**前に** `diary_state.is_active()` を判定。activeなら:
  - `text` → `_spawn(diary_collector.handle_text(text, reply_token))`
  - `image`/`file` → `_spawn(diary_collector.handle_photo(mid, reply_token))`
  - 通常の `_process` / `media_intake.handle` へは進ませない(`continue`)。
- 日記モードでない時の既存挙動は不変。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_diary.py
"""server: 日記モード中は diary_collector へ振り分け、通常Hermesへ流さない。"""
import json
import interactive.server as srv


def _post(client, text=None, mtype="text", mid="MID"):
    msg = {"type": mtype}
    if text is not None:
        msg["text"] = text
    if mtype != "text":
        msg["id"] = mid
    body = {"events": [{"type": "message", "message": msg,
                        "replyToken": "RT", "webhookEventId": "E1"}]}
    raw = json.dumps(body).encode()
    return client.post("/webhook", data=raw,
                       headers={"X-Line-Signature": "sig"})


def test_diary_active_text_goes_to_collector(monkeypatch):
    monkeypatch.setattr(srv, "verify_signature", lambda b, s: True)
    monkeypatch.setattr(srv, "_spawn", lambda fn: fn())     # 同期実行
    monkeypatch.setattr(srv.diary_state, "is_active", lambda: True)
    called = {}
    monkeypatch.setattr(srv.diary_collector, "handle_text",
                        lambda t, rt, **k: called.setdefault("text", (t, rt)))
    # 通常Hermesは呼ばれてはいけない
    monkeypatch.setattr(srv, "_process",
                        lambda *a, **k: called.setdefault("hermes", True))
    srv.app.test_client().post  # noqa
    r = _post(srv.app.test_client(), text="日記の中身")
    assert r.status_code == 200
    assert called["text"] == ("日記の中身", "RT")
    assert "hermes" not in called


def test_diary_inactive_uses_normal_path(monkeypatch):
    monkeypatch.setattr(srv, "verify_signature", lambda b, s: True)
    monkeypatch.setattr(srv, "_spawn", lambda fn: fn())
    monkeypatch.setattr(srv.diary_state, "is_active", lambda: False)
    called = {}
    monkeypatch.setattr(srv, "_process", lambda *a, **k: called.setdefault("hermes", True))
    r = _post(srv.app.test_client(), text="普通の質問")
    assert r.status_code == 200
    assert called.get("hermes") is True


def test_diary_active_photo_goes_to_collector(monkeypatch):
    monkeypatch.setattr(srv, "verify_signature", lambda b, s: True)
    monkeypatch.setattr(srv, "_spawn", lambda fn: fn())
    monkeypatch.setattr(srv.diary_state, "is_active", lambda: True)
    called = {}
    monkeypatch.setattr(srv.diary_collector, "handle_photo",
                        lambda mid, rt, **k: called.setdefault("photo", (mid, rt)))
    monkeypatch.setattr(srv.media_intake, "handle",
                        lambda *a, **k: called.setdefault("intake", True))
    r = _post(srv.app.test_client(), mtype="image", mid="PID")
    assert r.status_code == 200
    assert called["photo"] == ("PID", "RT")
    assert "intake" not in called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_server_diary.py -v`
Expected: FAIL(`AttributeError: module 'interactive.server' has no attribute 'diary_state'`)

- [ ] **Step 3: Write minimal implementation**

`interactive/server.py` の import 群(21行目 `from shared import line_client` の後)に追加:

```python
from interactive import diary_state
from interactive import diary_collector
```

webhook の `for event` ループ内、`reply_token = event.get("replyToken", "")` の直後(現132行目付近)を次のように差し替える:

```python
        reply_token = event.get("replyToken", "")
        # 日記モード中は日記コレクタへ(通常Hermes/画像intakeへは進ませない)
        if diary_state.is_active():
            if mtype == "text":
                t = msg["text"]
                _spawn(lambda tx=t, rt=reply_token: diary_collector.handle_text(tx, rt))
            else:  # image / file
                mid = msg.get("id", "")
                _spawn(lambda i=mid, rt=reply_token: diary_collector.handle_photo(i, rt))
            continue
        # 即200を返してLINEのタイムアウト→再配信を防ぐ。実処理は別スレッドへ。
        if mtype == "text":
            text = msg["text"]
            _spawn(lambda t=text, rt=reply_token: _process(t, rt, now_iso))
        else:  # image / file(PDF) → 取得→読解→Hermesへ
            mid = msg.get("id", "")
            _spawn(lambda i=mid, k=mtype, rt=reply_token: media_intake.handle(i, k, rt))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_server_diary.py tests/test_server.py tests/test_server_hermes_switch.py -v`
Expected: PASS(新規3件 + 既存server系の回帰なし)

- [ ] **Step 5: Commit**

```bash
git add interactive/server.py tests/test_server_diary.py
git commit -m "feat(diary): webhookで日記モード中はコレクタへ振り分け"
```

---

### Task 7: diary_web.py（本棚Webページ）＋ server 登録

**Files:**
- Create: `interactive/diary_web.py`
- Modify: `interactive/server.py`(Blueprint登録)
- Test: `tests/test_diary_web.py`

**Interfaces:**
- Consumes: `diary_store.list_entries` / `media_path`。
- Produces: Flask `Blueprint` `bp`:
  - `GET /diary` → 一覧HTML(1日1枚の広いカード・タイトル・日付・タグ・写真サムネ・清書本文)。
  - `GET /diary/media/<date>/<path:filename>` → 写真配信(`send_file`。存在しなければ404)。
- `server.py` に `from interactive import diary_web` と `app.register_blueprint(diary_web.bp)` を追加。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diary_web.py
"""diary_web: 日記の本棚ページ。テーブルでなく広いカードで見せる。"""
from interactive import diary_web
from interactive import diary_store
from flask import Flask


def _client(monkeypatch, entries):
    monkeypatch.setattr(diary_store, "list_entries", lambda: entries)
    app = Flask(__name__)
    app.register_blueprint(diary_web.bp)
    return app.test_client()


def test_list_renders_entries(monkeypatch):
    c = _client(monkeypatch, [
        {"date": "2026-07-07", "title": "当務の日", "tags": ["疲れ"],
         "body": "今日は当務だった。", "photos": [{"file": "1.jpg", "caption": "電車"}]},
    ])
    html = c.get("/diary").get_data(as_text=True)
    assert "当務の日" in html
    assert "2026-07-07" in html
    assert "疲れ" in html
    assert "今日は当務だった。" in html
    assert "/diary/media/2026-07-07/1.jpg" in html   # 写真サムネのsrc


def test_empty_state(monkeypatch):
    c = _client(monkeypatch, [])
    html = c.get("/diary").get_data(as_text=True)
    assert c.get("/diary").status_code == 200
    assert "まだ" in html          # 空状態の案内


def test_missing_media_is_404(monkeypatch, tmp_path):
    monkeypatch.setattr(diary_store, "DIARY_DIR", tmp_path)
    c = _client(monkeypatch, [])
    assert c.get("/diary/media/2026-07-07/nope.jpg").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_diary_web.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation**

```python
# interactive/diary_web.py
#!/usr/bin/env python3
"""日記の本棚Webページ。テーブルの窮屈さの逆=広いカードでゆったり見せる。

依存は diary_store のみ。HTMLは自己完結(外部CSS/JSなし)。
"""
import html as _html
from flask import Blueprint, abort, send_file

from interactive import diary_store

bp = Blueprint("diary", __name__)

_PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>📔 日記</title>
<style>
:root{{color-scheme:light dark}}
body{{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:0;
background:#faf8f4;color:#2b2b2b;line-height:1.9}}
@media(prefers-color-scheme:dark){{body{{background:#1a1a1a;color:#e8e6e2}}}}
header{{padding:28px 20px 8px;font-size:26px;font-weight:700}}
.wrap{{max-width:720px;margin:0 auto;padding:12px 16px 60px}}
.card{{background:#fff;border-radius:16px;padding:22px 24px;margin:18px 0;
box-shadow:0 2px 14px rgba(0,0,0,.06)}}
@media(prefers-color-scheme:dark){{.card{{background:#262626;box-shadow:none}}}}
.date{{font-size:13px;opacity:.6}}
.title{{font-size:20px;font-weight:700;margin:2px 0 10px}}
.tags{{margin:0 0 12px}}
.tag{{display:inline-block;background:#efe9dd;border-radius:999px;
padding:3px 12px;font-size:12px;margin-right:6px}}
@media(prefers-color-scheme:dark){{.tag{{background:#3a3a3a}}}}
.body{{white-space:pre-wrap;font-size:16px}}
.photos{{margin-top:14px;display:flex;flex-wrap:wrap;gap:10px}}
.photos img{{width:100%;max-width:220px;border-radius:12px}}
.empty{{opacity:.6;text-align:center;padding:60px 0}}
</style></head><body>
<header>📔 日記</header><div class="wrap">{cards}</div></body></html>"""


def _card(e: dict) -> str:
    date = _html.escape(e.get("date", ""))
    title = _html.escape(e.get("title", ""))
    body = _html.escape(e.get("body", ""))
    tags = "".join(f'<span class="tag">{_html.escape(str(t))}</span>'
                   for t in e.get("tags", []))
    imgs = "".join(
        f'<img src="/diary/media/{date}/{_html.escape(p.get("file", ""))}" '
        f'alt="{_html.escape(p.get("caption", ""))}" loading="lazy">'
        for p in e.get("photos", []))
    photos = f'<div class="photos">{imgs}</div>' if imgs else ""
    return (f'<div class="card"><div class="date">{date}</div>'
            f'<div class="title">{title}</div>'
            f'<div class="tags">{tags}</div>'
            f'<div class="body">{body}</div>{photos}</div>')


@bp.get("/diary")
def diary_index():
    entries = diary_store.list_entries()
    if not entries:
        cards = '<div class="empty">まだ日記はないよ。夜に書こう📔</div>'
    else:
        cards = "".join(_card(e) for e in entries)
    return _PAGE.format(cards=cards)


@bp.get("/diary/media/<date>/<path:filename>")
def diary_media(date, filename):
    p = diary_store.media_path(date, filename)
    if not p.exists():
        abort(404)
    return send_file(str(p))
```

`interactive/server.py` に登録(import追加 + `app = Flask(__name__)` の直後):

```python
from interactive import diary_web
# ... app = Flask(__name__) の後 ...
app.register_blueprint(diary_web.bp)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_diary_web.py -v`
Expected: PASS(3件)

- [ ] **Step 5: Commit**

```bash
git add interactive/diary_web.py interactive/server.py tests/test_diary_web.py
git commit -m "feat(diary): 本棚Webページ(/diary)を追加"
```

---

### Task 8: cron 声かけ（diary_prompt.py）＋ setup_cron.sh ＋ home-hub 登録

**Files:**
- Create: `diary_prompt.py`(リポジトリ直下)
- Modify: `setup_cron.sh`(20:00 の行を追加)
- Modify: `home-hub/services.json`(本棚に日記を追加)
- Test: `tests/test_diary_prompt.py`

**Interfaces:**
- Consumes: `diary_collector.finalize_timeout`, `diary_state.start`, `shared.line_client.push`。
- Produces: `diary_prompt.run(*, now_iso=None, finalize=..., start=..., push=...) -> None` — ①古い下書きがあれば `finalize_timeout` で確定 → ②`diary_state.start(today)` → ③「今日どうだった?」を push。`__main__` で `run()`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diary_prompt.py
"""diary_prompt: 20時の声かけ。古い下書きを確定してから今日の日記モードを開始。"""
import diary_prompt


def test_run_finalizes_then_starts_then_pushes(monkeypatch):
    events = []
    monkeypatch.setattr(diary_prompt, "finalize_timeout",
                        lambda **k: events.append("finalize") or False)
    monkeypatch.setattr(diary_prompt.diary_state, "start",
                        lambda date, now: events.append(("start", date)))
    monkeypatch.setattr(diary_prompt.line_client, "push",
                        lambda text: events.append(("push", text)) or True)
    diary_prompt.run(now_iso="2026-07-07T20:00:00+09:00")
    assert events[0] == "finalize"
    assert events[1] == ("start", "2026-07-07")
    assert events[2][0] == "push"
    assert "今日" in events[2][1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_diary_prompt.py -v`
Expected: FAIL(`ModuleNotFoundError: diary_prompt`)

- [ ] **Step 3: Write minimal implementation**

```python
# diary_prompt.py (リポジトリ直下)
#!/usr/bin/env python3
"""20時の日記の声かけ。cronから叩く。

①古い下書きがあれば確定 → ②今日の日記モード開始 → ③「今日どうだった?」をLINE push。
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from interactive import diary_state
from interactive.diary_collector import finalize_timeout
from shared import line_client

_JST = timezone(timedelta(hours=9))
_GREETING = "今日はどうだった?📔 一日を教えて。箇条書きでもいいよ。書き終わったら「終わり」って言ってね。"


def run(*, now_iso=None, finalize=finalize_timeout, start=diary_state.start,
        push=line_client.push) -> None:
    now_iso = now_iso or datetime.now(_JST).isoformat(timespec="seconds")
    try:
        finalize(now_iso=now_iso)
    except Exception as e:
        print(f"[WARN] diary_prompt finalize: {e}")
    start(now_iso[:10], now=now_iso)
    push(_GREETING)


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_diary_prompt.py -v`
Expected: PASS(1件)

- [ ] **Step 5: cron行を setup_cron.sh に追加**

`setup_cron.sh` の heredoc(`# ======== LINE秘書ブリーフィング ========` ブロック)内、朝5:30の行の下に追加:

```bash
# 夜20:00: 日記の声かけ(今日どうだった?)
0 20 * * * cd $SCRIPT_DIR && $PYTHON $SCRIPT_DIR/diary_prompt.py >> $LOG_DIR/diary.log 2>&1
```

- [ ] **Step 6: home-hub 本棚へ登録**

`home-hub/services.json` の「アプリ棚」の services 配列末尾に追加(日記ページは interactive サーバ :8800 が配信):

```json
        {
          "id": "diary",
          "name": "日記",
          "emoji": "📔",
          "desc": "夜にHermesが聞いてくれる日記（写真つき・自動で清書）",
          "port": 8800,
          "path": "/diary"
        }
```

- [ ] **Step 7: 全体テスト＋コミット**

Run: `venv/bin/python -m pytest tests/ -q`
Expected: 既存＋新規すべてPASS(回帰なし)

```bash
git add diary_prompt.py setup_cron.sh home-hub/services.json tests/test_diary_prompt.py
git commit -m "feat(diary): 20時の声かけcron + home-hub本棚に日記を登録"
```

- [ ] **Step 8: cron を実機反映(手動・1回)**

Run: `bash setup_cron.sh && crontab -l | grep diary`
Expected: `0 20 * * * ... diary_prompt.py` が表示される

---

## 手動スモーク（全タスク後・任意）

1. `venv/bin/python diary_prompt.py` を実行 → LINEに「今日どうだった?📔」が届く。
2. LINEで「・当務だった ・疲れた」と送る → 「メモしたよ📔 これでいい?」が返る。
3. 写真を送る → 「写真もらったよ📸」が返る。
4. 「おけ」と送る → 清書された日記が表示され「これでいい?」。
5. 「いいよ」と送る → 「保存したよ📔」。
6. ブラウザ/スマホ(Tailscale)で `:8800/diary` を開く → その日のカードに清書本文と写真サムネが出る。
7. home-hub(:7777)の本棚に「📔 日記」が並ぶ。

## Self-Review（記入済み）

- **Spec coverage**: 20時声かけ=Task8 / 会話収集・肯定スイッチ=Task5 / 忠実清書=Task2 / 写真キャプション=Task5(handle_photo) / 本棚ページ=Task7 / ローカル保存・原文保持=Task1,5 / 状態永続化=Task4 / 普通のHermesと分離=Task6 / 清書失敗フォールバック=Task2 / 時間切れ自動保存=Task5,8 / 手動「日記」開始=※下記メモ。
- **手動「日記」開始**: specの「20時を逃しても自分から『日記』で開始」は、Task6の日記モード非active時に text=="日記" を検出して `diary_prompt.run()` 相当(start+挨拶)を呼ぶ小分岐で満たす。Task6 Step3 に次を足す(webhook、日記非active・text時): `if mtype=="text" and msg["text"].strip()=="日記": _spawn(lambda rt=reply_token: diary_collector.start_manual(rt)); continue` とし、`diary_collector.start_manual(reply_token)` = `diary_state.start(today); reply(reply_token, 挨拶)` を実装(Task5に薄い関数として追加、テスト1件)。**この追補を Task6 実装時に必ず含めること。**
- **Placeholder scan**: なし(全ステップに実コード)。
- **Type consistency**: `save`/`save_photo`/`list_entries`/`media_path`(store)、`is_active`/`phase`/`date`/`raw`/`captions`/`photos`/`set_confirming`/`composed`/`reopen`/`clear`/`start`(state)、`classify`(classify)、`compose`(compose)、`handle_text`/`handle_photo`/`finalize_timeout`/`start_manual`(collector) — タスク間で名称・引数一致を確認済み。
```
