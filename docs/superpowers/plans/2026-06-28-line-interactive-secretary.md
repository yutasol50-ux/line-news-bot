# LINE対話秘書「書いたら実行」 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LINEに日本語で書くと、Geminiが意図を解釈してGoogleカレンダーに予定を書き込み/Notionにメモを追記し、結果をLINEで返す対話秘書を、既存`line-news-bot`に追加する。

**Architecture:** WSL常駐のFlask Webhookサーバーが、Tailscale Funnel経由でLINEの着信を受ける。署名検証 → Gemini(REST, function calling)で`{action, params}`抽出 → アクション実行(Calendar/Notion)→ LINE Reply APIで返信。朝の通達(push型)は`briefing/`に分離して維持。

**Tech Stack:** Python 3.12, Flask, requests(Gemini/Notion/LINE REST), google-api-python-client + google-auth-oauthlib(Calendar OAuth), systemd(常駐), Tailscale Funnel(公開), Gemini 2.5-flash-lite.

## Global Constraints

- 既存の朝の通達(`secretary.py`)を壊さない。ファイル移動時はcronとWindowsタスク両方を更新し、動作確認するまでコミットしない。
- 秘密情報(トークン・OAuth JSON)は`.env`または`secrets/`に置き、必ず`.gitignore`。コードに直書き禁止。
- Geminiモデルは `gemini-2.5-flash-lite` 固定(2.5-flashは無料枠1日20リクエストのため不可)。
- LINE返信は Reply API(無料・無制限)。Push(朝の通達)は月200通枠を意識し1日1通まで。
- 日時は全てJST(+09:00)・ISO8601で扱う。
- 作業ブランチ: `feature/interactive-secretary`(mainへ直接コミットしない)。
- 全コマンドはプロジェクト直下 `/home/yuta/line/line-news-bot` 基準。Pythonは `venv/bin/python`、テストは `venv/bin/python -m pytest`。

---

### Task 1: 作業ブランチと依存・環境スキャフォールド

**Files:**
- Modify: `requirements.txt`(無ければCreate)
- Modify: `.env.example`
- Modify: `.gitignore`
- Create: `secrets/.gitkeep`
- Create: `tests/__init__.py`

**Interfaces:**
- Produces: 後続タスクが使うパッケージ(flask, google-api-python-client, google-auth-oauthlib, google-auth-httplib2, pytest)と `.env` キー定義。

- [ ] **Step 1: ブランチ作成**

```bash
cd /home/yuta/line/line-news-bot
git checkout -b feature/interactive-secretary
```

- [ ] **Step 2: 依存をインストール**

```bash
venv/bin/python -m pip install flask google-api-python-client google-auth-oauthlib google-auth-httplib2 pytest
```

- [ ] **Step 3: requirements.txt を更新(現状を固定)**

```bash
venv/bin/python -m pip freeze > requirements.txt
```

- [ ] **Step 4: .env.example に新キーを追記**

`.env.example` の末尾に追加:

```
# --- 対話秘書(interactive) ---
GEMINI_API_KEY=your_gemini_api_key
LINE_CHANNEL_SECRET=your_line_channel_secret
NOTION_TOKEN=your_notion_internal_connection_token
NOTION_MEMO_DB_ID=your_notion_database_id
GOOGLE_CALENDAR_ID=primary
GCAL_CLIENT_SECRET_PATH=secrets/gcal_client.json
GCAL_TOKEN_PATH=secrets/gcal_token.json
```

- [ ] **Step 5: .gitignore に secrets とトークンを追加**

`.gitignore` に追記(既存行は残す):

```
secrets/*
!secrets/.gitkeep
```

- [ ] **Step 6: ディレクトリとプレースホルダ作成**

```bash
mkdir -p secrets tests interactive/actions briefing shared
touch secrets/.gitkeep tests/__init__.py
```

- [ ] **Step 7: コミット**

```bash
git add requirements.txt .env.example .gitignore secrets/.gitkeep tests/__init__.py
git commit -m "chore: 対話秘書の依存と環境スキャフォールドを追加"
```

---

### Task 2: ディレクトリ整理(briefing/分離)+ cron/タスク参照更新

朝の通達ファイルを`briefing/`へ移動し、参照を全て更新して**通達が壊れていないことを確認**する。

**Files:**
- Move: `secretary.py calendar_events.py weather.py news_headline.py daily_word.py` → `briefing/`
- Create: `briefing/__init__.py`
- Modify: `crontab`(`crontab -e` 相当)
- Modify: `C:\Users\yuwat\setup_line_task.ps1` とタスク再登録

**Interfaces:**
- Produces: `briefing/secretary.py`(エントリポイント。`data/`・`.env`はプロジェクト直下を参照し続ける)。

- [ ] **Step 1: ファイル移動**

```bash
cd /home/yuta/line/line-news-bot
git mv secretary.py calendar_events.py weather.py news_headline.py daily_word.py briefing/
touch briefing/__init__.py
```

- [ ] **Step 2: briefing内のパス基準を確認・修正**

`briefing/secretary.py`・`briefing/*.py` で `Path(__file__).parent` を使い`data/`や`.env`を指している箇所を、プロジェクト直下基準に修正する。例(`secretary.py`):

```python
# 修正前: DATA_DIR = Path(__file__).parent / "data"
# 修正後: プロジェクト直下を基準にする
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
```

同様に `briefing/calendar_events.py`・`weather.py`・`news_headline.py`・`daily_word.py` の `load_dotenv(Path(__file__).parent / ".env")` を `Path(__file__).resolve().parent.parent / ".env"` に修正。相互importは同一パッケージ内なので `from calendar_events import ...` のままでよい(同ディレクトリ)。

- [ ] **Step 3: dryで通達が壊れていないか確認**

```bash
venv/bin/python briefing/secretary.py dry
```

Expected: 6月◯日の通達本文(予定/天気/ニュース/一語)がエラーなく表示される。

- [ ] **Step 4: cron のパスを更新**

`crontab -e` で該当行を以下に変更(`secretary.py` → `briefing/secretary.py`):

```
30 5 * * * cd /home/yuta/line/line-news-bot && git pull --quiet 2>/dev/null; /home/yuta/line/line-news-bot/venv/bin/python3 /home/yuta/line/line-news-bot/briefing/secretary.py >> /home/yuta/line/line-news-bot/logs/secretary.log 2>&1
```

確認: `crontab -l | grep briefing/secretary.py` が1行返る。

- [ ] **Step 5: Windowsタスクの参照を更新して再登録**

`C:\Users\yuwat\setup_line_task.ps1` の `$wslArgs` 内パスを `briefing/secretary.py` に変更:

```powershell
$wslArgs = '-d Ubuntu -u yuta bash -c "cd /home/yuta/line/line-news-bot && /home/yuta/line/line-news-bot/venv/bin/python3 /home/yuta/line/line-news-bot/briefing/secretary.py >> /home/yuta/line/line-news-bot/logs/secretary.log 2>&1"'
```

再登録(`-Force`で上書き):

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\yuwat\setup_line_task.ps1'
```

- [ ] **Step 6: タスク手動実行で疎通(当日送信済みならスキップ表示でOK)**

```bash
powershell.exe -NoProfile -Command "Start-ScheduledTask -TaskName 'LINE_Secretary_Briefing'; Start-Sleep -Seconds 12; (Get-ScheduledTaskInfo -TaskName 'LINE_Secretary_Briefing').LastTaskResult"
```

Expected: `0`(正常終了)。`logs/secretary.log` に `送信完了` か `[SKIP] 本日は送信済み` が出る。

- [ ] **Step 7: コミット**

```bash
git add -A
git commit -m "refactor: 朝の通達を briefing/ に分離し cron/タスク参照を更新"
```

---

### Task 3: shared/line_client.py(push + reply 共通クライアント)

既存`line_send.py`を`shared/`へ吸収し、Reply API関数を追加する。

**Files:**
- Create: `shared/__init__.py`, `shared/line_client.py`
- Test: `tests/test_line_client.py`
- Delete: `line_send.py`(briefingが参照していれば先に付け替え)

**Interfaces:**
- Produces:
  - `push(text: str) -> bool`(既存send_line相当。`LINE_ACCESS_TOKEN`/`LINE_USER_ID`使用、4900字分割)
  - `reply(reply_token: str, text: str) -> bool`(Reply API。失敗時はpushにフォールバック)

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_line_client.py`:

```python
import json
from unittest.mock import patch, MagicMock
from shared import line_client


def test_reply_posts_to_reply_endpoint():
    captured = {}
    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        m = MagicMock(); m.status_code = 200; m.text = "{}"
        return m
    with patch("shared.line_client.requests.post", side_effect=fake_post):
        ok = line_client.reply("RTOKEN", "やったよ")
    assert ok is True
    assert captured["url"] == "https://api.line.me/v2/bot/message/reply"
    assert captured["json"]["replyToken"] == "RTOKEN"
    assert captured["json"]["messages"][0]["text"] == "やったよ"
```

- [ ] **Step 2: テスト失敗を確認**

```bash
venv/bin/python -m pytest tests/test_line_client.py -v
```

Expected: FAIL(`shared.line_client` が無い / `reply` 未定義)

- [ ] **Step 3: 実装**

`shared/__init__.py` は空。`shared/line_client.py`:

```python
#!/usr/bin/env python3
"""LINE送受信クライアント。push(自発送信) と reply(応答) を提供。"""
import os
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

LINE_ACCESS_TOKEN = os.environ["LINE_ACCESS_TOKEN"]
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")
_HEADERS = {
    "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}


def push(text: str) -> bool:
    chunks = [text[i:i + 4900] for i in range(0, len(text), 4900)] or [""]
    success = True
    for chunk in chunks:
        try:
            resp = requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers=_HEADERS,
                json={"to": LINE_USER_ID, "messages": [{"type": "text", "text": chunk}]},
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"[ERROR] LINE push失敗: {resp.status_code} {resp.text[:200]}")
                success = False
            time.sleep(1)
        except Exception as e:
            print(f"[ERROR] LINE push例外: {e}")
            success = False
    return success


def reply(reply_token: str, text: str) -> bool:
    """Reply APIで応答。replyTokenは1回・約1分有効。失敗時はpushにフォールバック。"""
    text = text[:4900]
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers=_HEADERS,
            json={"replyToken": reply_token, "messages": [{"type": "text", "text": text}]},
            timeout=30,
        )
        if resp.status_code == 200:
            return True
        print(f"[WARN] reply失敗→pushへ: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[WARN] reply例外→pushへ: {e}")
    return push(text)
```

- [ ] **Step 4: briefing側の参照を付け替え、旧ファイル削除**

`briefing/secretary.py` の `from line_send import send_line` を `from shared.line_client import push as send_line` に変更。動作確認:

```bash
venv/bin/python briefing/secretary.py dry
git rm line_send.py
```

- [ ] **Step 5: テスト合格を確認**

```bash
venv/bin/python -m pytest tests/test_line_client.py -v
```

Expected: PASS

- [ ] **Step 6: コミット**

```bash
git add -A
git commit -m "feat: LINE push/reply を shared/line_client に統合"
```

---

### Task 4: interactive/intent.py(Gemini で 文章→アクション)

**Files:**
- Create: `interactive/__init__.py`, `interactive/intent.py`
- Test: `tests/test_intent.py`

**Interfaces:**
- Produces:
  - `parse_intent(text: str, now_iso: str) -> dict`
    返り値: `{"action": "add_calendar_event"|"add_memo"|"none", "params": dict, "message": str}`
    - add_calendar_event の params: `{"title": str, "start": ISO8601, "end": ISO8601|None, "all_day": bool}`
    - add_memo の params: `{"content": str, "tags": list[str]}`
    - none の params: `{}`、message に短い返信文
  - 内部: `_call_gemini(payload: dict) -> dict`(テストで差し替える境界。HTTP呼び出しのみ)

- [ ] **Step 1: 失敗するテストを書く(Geminiレスポンスをモック)**

`tests/test_intent.py`:

```python
from unittest.mock import patch
from interactive import intent

NOW = "2026-06-28T22:00:00+09:00"

def _gemini_function_call(name, args):
    return {"candidates": [{"content": {"parts": [
        {"functionCall": {"name": name, "args": args}}
    ]}}]}

def test_calendar_intent_parsed():
    fake = _gemini_function_call("add_calendar_event", {
        "title": "歯医者", "start": "2026-06-29T14:00:00+09:00",
        "end": "2026-06-29T15:00:00+09:00", "all_day": False,
    })
    with patch("interactive.intent._call_gemini", return_value=fake):
        out = intent.parse_intent("明日14時に歯医者", NOW)
    assert out["action"] == "add_calendar_event"
    assert out["params"]["title"] == "歯医者"
    assert out["params"]["start"] == "2026-06-29T14:00:00+09:00"

def test_memo_intent_parsed():
    fake = _gemini_function_call("add_memo", {"content": "牛乳を買う", "tags": ["買い物"]})
    with patch("interactive.intent._call_gemini", return_value=fake):
        out = intent.parse_intent("牛乳買うのメモ", NOW)
    assert out["action"] == "add_memo"
    assert out["params"]["content"] == "牛乳を買う"

def test_no_function_call_is_none():
    fake = {"candidates": [{"content": {"parts": [{"text": "こんにちは!"}]}}]}
    with patch("interactive.intent._call_gemini", return_value=fake):
        out = intent.parse_intent("こんにちは", NOW)
    assert out["action"] == "none"
    assert "こんにちは" in out["message"]
```

- [ ] **Step 2: テスト失敗を確認**

```bash
venv/bin/python -m pytest tests/test_intent.py -v
```

Expected: FAIL(`interactive.intent` 無し)

- [ ] **Step 3: 実装**

`interactive/__init__.py` は空。`interactive/intent.py`:

```python
#!/usr/bin/env python3
"""Gemini(REST, function calling)で 自然文 → 構造化アクション に変換する。"""
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = "gemini-2.5-flash-lite"
ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
)

_TOOLS = [{"function_declarations": [
    {
        "name": "add_calendar_event",
        "description": "ユーザーが予定・アポイント・締切などを記録したい時に呼ぶ。",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "予定の件名"},
                "start": {"type": "string", "description": "開始日時 ISO8601 (+09:00)。時刻不明なら日付の00:00"},
                "end": {"type": "string", "description": "終了日時 ISO8601。不明ならstart+1時間"},
                "all_day": {"type": "boolean", "description": "時刻指定が無い終日予定ならtrue"},
            },
            "required": ["title", "start", "all_day"],
        },
    },
    {
        "name": "add_memo",
        "description": "予定ではない覚え書き・買い物・アイデア・あとで調べる事をメモする時に呼ぶ。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "メモ本文"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "任意の分類タグ"},
            },
            "required": ["content"],
        },
    },
]}]


def _system_instruction(now_iso: str) -> dict:
    return {"parts": [{"text":
        "あなたは渡辺さんの秘書。ユーザーの日本語メッセージを読み、"
        "予定なら add_calendar_event、覚え書きなら add_memo を呼ぶ。"
        "雑談や判断不能な場合は関数を呼ばず、短く親しみやすい日本語で返す。"
        f"現在の日時(JST)は {now_iso}。相対表現(明日/今週末等)はこれを基準に絶対日時へ変換する。"
    }]}


def _call_gemini(payload: dict) -> dict:
    """Gemini generateContent を叩く境界。テストで差し替える。"""
    resp = requests.post(
        ENDPOINT,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def parse_intent(text: str, now_iso: str) -> dict:
    payload = {
        "system_instruction": _system_instruction(now_iso),
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "tools": _TOOLS,
    }
    data = _call_gemini(payload)
    parts = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    for part in parts:
        fc = part.get("functionCall")
        if fc:
            name = fc.get("name")
            args = fc.get("args", {}) or {}
            if name == "add_calendar_event":
                return {"action": "add_calendar_event", "params": {
                    "title": args.get("title", "(無題)"),
                    "start": args.get("start"),
                    "end": args.get("end"),
                    "all_day": bool(args.get("all_day", False)),
                }, "message": ""}
            if name == "add_memo":
                return {"action": "add_memo", "params": {
                    "content": args.get("content", ""),
                    "tags": args.get("tags", []) or [],
                }, "message": ""}
    # 関数呼び出しが無ければ none。テキストをそのまま返信に使う。
    text_reply = next((p.get("text") for p in parts if p.get("text")), "うん、了解!")
    return {"action": "none", "params": {}, "message": text_reply}
```

- [ ] **Step 4: テスト合格を確認**

```bash
venv/bin/python -m pytest tests/test_intent.py -v
```

Expected: PASS(3件)

- [ ] **Step 5: コミット**

```bash
git add interactive/__init__.py interactive/intent.py tests/test_intent.py
git commit -m "feat: Gemini function calling で意図解釈する intent モジュール"
```

---

### Task 5: interactive/actions/notion_memo.py(Notion追記)

**Files:**
- Create: `interactive/actions/__init__.py`, `interactive/actions/notion_memo.py`
- Test: `tests/test_notion_memo.py`

**Interfaces:**
- Consumes: `.env` の `NOTION_TOKEN`, `NOTION_MEMO_DB_ID`
- Produces: `add(content: str, tags: list[str] | None = None, when_iso: str | None = None) -> str`(作成ページのURLを返す。失敗時は例外)

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_notion_memo.py`:

```python
from unittest.mock import patch, MagicMock
from interactive.actions import notion_memo

def test_add_posts_page_with_title_and_db():
    captured = {}
    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        m = MagicMock(); m.status_code = 200
        m.json.return_value = {"url": "https://notion.so/abc"}
        return m
    with patch("interactive.actions.notion_memo.requests.post", side_effect=fake_post):
        url = notion_memo.add("牛乳を買う", tags=["買い物"])
    assert url == "https://notion.so/abc"
    assert captured["url"] == "https://api.notion.com/v1/pages"
    assert captured["json"]["parent"]["database_id"]  # DB指定がある
    # タイトルプロパティに本文が入る
    title = captured["json"]["properties"]["名前"]["title"][0]["text"]["content"]
    assert title == "牛乳を買う"
    assert captured["headers"]["Authorization"].startswith("Bearer ")
```

- [ ] **Step 2: テスト失敗を確認**

```bash
venv/bin/python -m pytest tests/test_notion_memo.py -v
```

Expected: FAIL(モジュール無し)

- [ ] **Step 3: 実装**

`interactive/actions/__init__.py` は空。`interactive/actions/notion_memo.py`:

```python
#!/usr/bin/env python3
"""Notion APIでメモDBに行(ページ)を追記する。"""
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_MEMO_DB_ID = os.environ["NOTION_MEMO_DB_ID"]
_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def add(content: str, tags: list[str] | None = None, when_iso: str | None = None) -> str:
    """メモDBに1行追加。DBは『名前(title)/日付(date)/タグ(multi_select)』を想定。"""
    props = {
        "名前": {"title": [{"text": {"content": content[:1900]}}]},
    }
    if when_iso:
        props["日付"] = {"date": {"start": when_iso}}
    if tags:
        props["タグ"] = {"multi_select": [{"name": t} for t in tags]}

    resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers=_HEADERS,
        json={"parent": {"database_id": NOTION_MEMO_DB_ID}, "properties": props},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Notion追記失敗: {resp.status_code} {resp.text[:300]}")
    return resp.json().get("url", "")
```

- [ ] **Step 4: テスト合格を確認**

```bash
venv/bin/python -m pytest tests/test_notion_memo.py -v
```

Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add interactive/actions/__init__.py interactive/actions/notion_memo.py tests/test_notion_memo.py
git commit -m "feat: Notion メモ追記アクション"
```

---

### Task 6: interactive/actions/calendar_add.py + OAuth初回認証スクリプト

**Files:**
- Create: `interactive/actions/calendar_add.py`
- Create: `interactive/gcal_auth.py`(初回認証を通すワンタイムスクリプト)
- Test: `tests/test_calendar_add.py`

**Interfaces:**
- Consumes: `.env` の `GOOGLE_CALENDAR_ID`, `GCAL_CLIENT_SECRET_PATH`, `GCAL_TOKEN_PATH`
- Produces:
  - `add(title: str, start_iso: str, end_iso: str | None = None, all_day: bool = False) -> str`(作成イベントのhtmlLinkを返す)
  - 内部: `_build_service()`(認証済みCalendarサービスを返す。テストで差し替える境界)

- [ ] **Step 1: 失敗するテストを書く(Google serviceをモック)**

`tests/test_calendar_add.py`:

```python
from unittest.mock import patch, MagicMock
from interactive.actions import calendar_add

def test_timed_event_inserted():
    inserted = {}
    fake_events = MagicMock()
    def fake_insert(calendarId=None, body=None):
        inserted["calendarId"] = calendarId
        inserted["body"] = body
        ex = MagicMock(); ex.execute.return_value = {"htmlLink": "https://cal/x"}
        return ex
    fake_events.insert.side_effect = fake_insert
    fake_service = MagicMock(); fake_service.events.return_value = fake_events
    with patch("interactive.actions.calendar_add._build_service", return_value=fake_service):
        link = calendar_add.add("歯医者", "2026-06-29T14:00:00+09:00",
                                 "2026-06-29T15:00:00+09:00", all_day=False)
    assert link == "https://cal/x"
    assert inserted["body"]["summary"] == "歯医者"
    assert inserted["body"]["start"]["dateTime"] == "2026-06-29T14:00:00+09:00"

def test_all_day_event_uses_date():
    fake_events = MagicMock()
    ex = MagicMock(); ex.execute.return_value = {"htmlLink": "https://cal/y"}
    fake_events.insert.return_value = ex
    fake_service = MagicMock(); fake_service.events.return_value = fake_events
    with patch("interactive.actions.calendar_add._build_service", return_value=fake_service):
        calendar_add.add("健康診断", "2026-07-01T00:00:00+09:00", None, all_day=True)
    body = fake_events.insert.call_args.kwargs["body"]
    assert body["start"]["date"] == "2026-07-01"
    assert "dateTime" not in body["start"]
```

- [ ] **Step 2: テスト失敗を確認**

```bash
venv/bin/python -m pytest tests/test_calendar_add.py -v
```

Expected: FAIL(モジュール無し)

- [ ] **Step 3: 実装(calendar_add.py)**

```python
#!/usr/bin/env python3
"""Google Calendar API で予定を作成する。"""
import os
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

_BASE = Path(__file__).resolve().parent.parent.parent
CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
TOKEN_PATH = _BASE / os.environ.get("GCAL_TOKEN_PATH", "secrets/gcal_token.json")
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _build_service():
    """保存済みトークンから Calendar service を作る。テストで差し替える境界。"""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def add(title: str, start_iso: str, end_iso: str | None = None, all_day: bool = False) -> str:
    service = _build_service()
    if all_day:
        day = start_iso[:10]  # YYYY-MM-DD
        end_day = (datetime.fromisoformat(start_iso) + timedelta(days=1)).date().isoformat()
        body = {"summary": title, "start": {"date": day}, "end": {"date": end_day}}
    else:
        if not end_iso:
            end_iso = (datetime.fromisoformat(start_iso) + timedelta(hours=1)).isoformat()
        body = {
            "summary": title,
            "start": {"dateTime": start_iso, "timeZone": "Asia/Tokyo"},
            "end": {"dateTime": end_iso, "timeZone": "Asia/Tokyo"},
        }
    created = service.events().insert(calendarId=CALENDAR_ID, body=body).execute()
    return created.get("htmlLink", "")
```

- [ ] **Step 4: テスト合格を確認**

```bash
venv/bin/python -m pytest tests/test_calendar_add.py -v
```

Expected: PASS(2件)

- [ ] **Step 5: 初回認証スクリプトを作成**

`interactive/gcal_auth.py`:

```python
#!/usr/bin/env python3
"""一度だけ実行してGoogleカレンダー書き込みを承認し、トークンを保存する。
WSLではブラウザが開けないので run_console 相当(URLを表示→コード貼り付け)を使う。"""
import os
from pathlib import Path
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

_BASE = Path(__file__).resolve().parent.parent
load_dotenv(_BASE / ".env")
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CLIENT = _BASE / os.environ.get("GCAL_CLIENT_SECRET_PATH", "secrets/gcal_client.json")
TOKEN = _BASE / os.environ.get("GCAL_TOKEN_PATH", "secrets/gcal_token.json")

flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
# WSL: ローカルサーバー方式。表示されたURLをWindows側ブラウザで開いて承認する。
creds = flow.run_local_server(port=0, open_browser=False)
TOKEN.write_text(creds.to_json(), encoding="utf-8")
print(f"✅ 認証完了。トークンを保存: {TOKEN}")
```

注: このスクリプトの実行(GCPコンソールでのAPI有効化・OAuthクライアント作成・client JSON配置)は Task 9 の運用手順で人間が一度だけ行う。ここではコードのみ用意。

- [ ] **Step 6: コミット**

```bash
git add interactive/actions/calendar_add.py interactive/gcal_auth.py tests/test_calendar_add.py
git commit -m "feat: Google Calendar 書き込みアクションと初回認証スクリプト"
```

---

### Task 7: interactive/server.py(Flask Webhook + 署名検証 + ディスパッチ)

**Files:**
- Create: `interactive/server.py`
- Create: `interactive/dispatch.py`(intent結果→アクション実行→返信文 のオーケストレーション)
- Test: `tests/test_server.py`, `tests/test_dispatch.py`

**Interfaces:**
- Consumes: `intent.parse_intent`, `calendar_add.add`, `notion_memo.add`, `line_client.reply`, `.env` の `LINE_CHANNEL_SECRET`
- Produces:
  - `dispatch.handle(text: str, now_iso: str) -> str`(実行して返信文を返す。例外は捕捉し正直な失敗文)
  - `server.verify_signature(body: bytes, signature: str) -> bool`
  - Flask app: `POST /webhook`(署名検証→各messageイベントを handle→reply)、`GET /health`

- [ ] **Step 1: dispatch の失敗するテストを書く**

`tests/test_dispatch.py`:

```python
from unittest.mock import patch
from interactive import dispatch

NOW = "2026-06-28T22:00:00+09:00"

def test_dispatch_calendar(monkeypatch):
    monkeypatch.setattr(dispatch.intent, "parse_intent", lambda t, n: {
        "action": "add_calendar_event",
        "params": {"title": "歯医者", "start": "2026-06-29T14:00:00+09:00",
                   "end": None, "all_day": False}, "message": ""})
    monkeypatch.setattr(dispatch.calendar_add, "add", lambda **k: "https://cal/x")
    msg = dispatch.handle("明日14時歯医者", NOW)
    assert "歯医者" in msg and "登録" in msg

def test_dispatch_memo(monkeypatch):
    monkeypatch.setattr(dispatch.intent, "parse_intent", lambda t, n: {
        "action": "add_memo", "params": {"content": "牛乳", "tags": []}, "message": ""})
    monkeypatch.setattr(dispatch.notion_memo, "add", lambda **k: "https://notion/x")
    msg = dispatch.handle("牛乳メモ", NOW)
    assert "メモ" in msg

def test_dispatch_failure_is_honest(monkeypatch):
    monkeypatch.setattr(dispatch.intent, "parse_intent", lambda t, n: {
        "action": "add_memo", "params": {"content": "x", "tags": []}, "message": ""})
    def boom(**k): raise RuntimeError("api down")
    monkeypatch.setattr(dispatch.notion_memo, "add", boom)
    msg = dispatch.handle("メモして", NOW)
    assert "失敗" in msg
```

- [ ] **Step 2: テスト失敗を確認**

```bash
venv/bin/python -m pytest tests/test_dispatch.py -v
```

Expected: FAIL(`interactive.dispatch` 無し)

- [ ] **Step 3: dispatch.py 実装**

```python
#!/usr/bin/env python3
"""intent結果をアクションに振り分け、LINE返信用の日本語文を返す。"""
from interactive import intent
from interactive.actions import calendar_add, notion_memo


def _fmt_dt(iso: str | None, all_day: bool) -> str:
    if not iso:
        return ""
    return iso[:10] if all_day else iso[:16].replace("T", " ")


def handle(text: str, now_iso: str) -> str:
    try:
        result = intent.parse_intent(text, now_iso)
    except Exception as e:
        print(f"[ERROR] intent: {e}")
        return "ごめん、ちょっと調子が悪いみたい。もう一回送ってくれる?"

    action = result["action"]
    p = result["params"]
    try:
        if action == "add_calendar_event":
            calendar_add.add(title=p["title"], start_iso=p["start"],
                             end_iso=p.get("end"), all_day=p["all_day"])
            return f"📅 {_fmt_dt(p['start'], p['all_day'])} {p['title']} を登録したよ"
        if action == "add_memo":
            notion_memo.add(content=p["content"], tags=p.get("tags") or None)
            tag = f"({'・'.join(p['tags'])})" if p.get("tags") else ""
            return f"📝 メモに追加したよ{tag}:{p['content']}"
        return result.get("message") or "うん、了解!"
    except Exception as e:
        print(f"[ERROR] action {action}: {e}")
        target = "カレンダー" if action == "add_calendar_event" else "メモ"
        return f"⚠️ {target}の登録に失敗しちゃった。後で確認してね。"
```

- [ ] **Step 4: dispatch テスト合格**

```bash
venv/bin/python -m pytest tests/test_dispatch.py -v
```

Expected: PASS(3件)

- [ ] **Step 5: server の署名検証テストを書く**

`tests/test_server.py`:

```python
import base64, hashlib, hmac, json
from unittest.mock import patch
import interactive.server as server

SECRET = "testsecret"

def _sign(body: bytes) -> str:
    return base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()

def test_verify_signature_ok(monkeypatch):
    monkeypatch.setattr(server, "CHANNEL_SECRET", SECRET)
    body = b'{"events":[]}'
    assert server.verify_signature(body, _sign(body)) is True

def test_verify_signature_ng(monkeypatch):
    monkeypatch.setattr(server, "CHANNEL_SECRET", SECRET)
    assert server.verify_signature(b'{"events":[]}', "wrong") is False

def test_webhook_dispatches_and_replies(monkeypatch):
    monkeypatch.setattr(server, "CHANNEL_SECRET", SECRET)
    replied = {}
    monkeypatch.setattr(server, "verify_signature", lambda b, s: True)
    monkeypatch.setattr(server.dispatch, "handle", lambda t, n: "OK登録")
    monkeypatch.setattr(server.line_client, "reply", lambda rt, msg: replied.update(rt=rt, msg=msg) or True)
    client = server.app.test_client()
    payload = {"events": [{"type": "message", "replyToken": "RT",
               "message": {"type": "text", "text": "明日歯医者"}}]}
    r = client.post("/webhook", data=json.dumps(payload),
                    headers={"X-Line-Signature": "x", "Content-Type": "application/json"})
    assert r.status_code == 200
    assert replied["msg"] == "OK登録"
```

- [ ] **Step 6: テスト失敗を確認**

```bash
venv/bin/python -m pytest tests/test_server.py -v
```

Expected: FAIL(`interactive.server` 無し)

- [ ] **Step 7: server.py 実装**

```python
#!/usr/bin/env python3
"""LINE Webhook受付。署名検証 → dispatch → reply。"""
import os
import base64
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, abort

from interactive import dispatch
from shared import line_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
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
```

- [ ] **Step 8: 全テスト合格を確認**

```bash
venv/bin/python -m pytest tests/ -v
```

Expected: PASS(全件)

- [ ] **Step 9: コミット**

```bash
git add interactive/server.py interactive/dispatch.py tests/test_server.py tests/test_dispatch.py
git commit -m "feat: Flask Webhook(署名検証)とアクション・ディスパッチ"
```

---

### Task 8: 公開設定(Tailscale Funnel)と LINE Webhook 登録 — 運用

外部設定が主。コード変更は無し。手順を実行し、結果を記録する。

**Files:**
- Create: `docs/setup-webhook.md`(実施手順と結果メモ)

- [ ] **Step 1: サーバーをローカル起動して疎通**

```bash
venv/bin/python interactive/server.py &
curl -s http://127.0.0.1:8800/health
```

Expected: `ok`

- [ ] **Step 2: Tailscale Funnel で 8800 を公開**

```bash
tailscale funnel --bg 8800
tailscale funnel status
```

Expected: `https://watanabeyuta-1.tail9c9905.ts.net/` が 8800 にプロキシされる表示。
公開URL = `https://watanabeyuta-1.tail9c9905.ts.net/webhook`

- [ ] **Step 3: 外部からhealth確認**

スマホ(Wi-Fi切断/モバイル回線)等のブラウザで `https://watanabeyuta-1.tail9c9905.ts.net/health` を開き `ok` を確認。

- [ ] **Step 4: LINE Developers で Webhook を登録**

LINE Developers コンソール → 該当チャネル → Messaging API設定:
- Webhook URL に `https://watanabeyuta-1.tail9c9905.ts.net/webhook` を設定
- 「Webhookの利用」をON
- 「検証」ボタンで Success を確認
- チャネルシークレットを `.env` の `LINE_CHANNEL_SECRET` に設定
- 応答メッセージ(自動応答)はOFF(秘書の返信と競合させない)

- [ ] **Step 5: 手順を docs に記録してコミット**

`docs/setup-webhook.md` に 公開URL・Funnelコマンド・LINE設定値(秘密は除く)を記録。

```bash
git add docs/setup-webhook.md
git commit -m "docs: Webhook公開とLINE登録の手順を記録"
```

---

### Task 9: WSL常駐(systemd)+ Google Calendar 初回認証 — 運用

秘書が24時間反応するための常駐化と、カレンダー書き込みの一回認証を行う。

**Files:**
- Create: `interactive/secretary-webhook.service`(systemd unit)
- Create: `interactive/run_server.sh`(起動ラッパ)

- [ ] **Step 1: Google Calendar の一回認証を通す**

GCPコンソールでの準備(人間が一度だけ):
1. Calendar API 有効化: https://console.cloud.google.com/apis/library/calendar-json.googleapis.com
2. OAuthクライアント(デスクトップアプリ)作成: https://console.cloud.google.com/apis/credentials → JSONをDL
3. DLしたJSONを `secrets/gcal_client.json` に配置

認証実行:

```bash
venv/bin/python interactive/gcal_auth.py
```

表示URLをWindows側ブラウザで開き承認 → `secrets/gcal_token.json` 生成を確認。書き込み疎通:

```bash
venv/bin/python -c "from interactive.actions import calendar_add; print(calendar_add.add('秘書テスト','2026-06-30T10:00:00+09:00',None,False))"
```

Expected: イベントのhtmlLinkが表示され、Googleカレンダーに「秘書テスト」が入る(確認後カレンダーから削除)。

- [ ] **Step 2: 起動ラッパ作成**

`interactive/run_server.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /home/yuta/line/line-news-bot
exec venv/bin/python interactive/server.py
```

```bash
chmod +x interactive/run_server.sh
```

- [ ] **Step 3: WSLのsystemd有効化を確認**

`/etc/wsl.conf` に以下が無ければ追記(要 `wsl --shutdown` 後に有効化。Windows PowerShellで実施):

```ini
[boot]
systemd=true
```

確認: `systemctl is-system-running` が `running` か `degraded` を返す(systemd有効)。

- [ ] **Step 4: systemd ユーザーサービスとして常駐**

`~/.config/systemd/user/secretary-webhook.service`(`interactive/secretary-webhook.service` をコピー):

```ini
[Unit]
Description=LINE Interactive Secretary Webhook
After=network-online.target

[Service]
ExecStart=/home/yuta/line/line-news-bot/interactive/run_server.sh
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

有効化:

```bash
mkdir -p ~/.config/systemd/user
cp interactive/secretary-webhook.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now secretary-webhook.service
loginctl enable-linger yuta   # ログオフ後も動かす
systemctl --user status secretary-webhook.service
```

Expected: `active (running)`。`curl -s localhost:8800/health` が `ok`。

- [ ] **Step 5: WSLを窓と無関係に常時起動させる(Windows側)**

Windowsログオン時にWSLを起動し続けるため、タスクスケジューラに常駐タスクを追加(`C:\Users\yuwat\setup_wsl_keepalive.ps1` を作成):

```powershell
$action  = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d Ubuntu -u yuta --exec sleep infinity"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "WSL_KeepAlive" -Action $action -Trigger $trigger -Settings $settings -Description "WSLを常時起動させ秘書Webhookを生かす" -Force
Start-ScheduledTask -TaskName "WSL_KeepAlive"
```

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\yuwat\setup_wsl_keepalive.ps1'
```

Expected: `wsl -l --running` に Ubuntu が出続ける。窓を全部閉じてもWSLが落ちない。

- [ ] **Step 6: コミット**

```bash
git add interactive/run_server.sh interactive/secretary-webhook.service
git commit -m "feat: Webhookのsystemd常駐とWSL常時起動の運用ファイル"
```

---

### Task 10: E2E確認

**Files:** なし(手動検証)

- [ ] **Step 1: 予定の往復**

LINEで「明日の15時に床屋」と送る。
Expected: 数秒で「📅 ◯◯ 床屋 を登録したよ」返信 + Googleカレンダーに入る。

- [ ] **Step 2: メモの往復**

LINEで「電池買うのメモ」と送る。
Expected: 「📝 メモに追加したよ:電池買う」返信 + NotionのメモDBに新規行。

- [ ] **Step 3: 雑談(none)**

LINEで「おはよう」と送る。
Expected: カレンダー/メモに何も起きず、短い返信が返る。

- [ ] **Step 4: PCスリープ耐性(任意)**

Windowsをスリープ→復帰、または別端末から `https://.../health` を確認し、依然 `ok`。スリープ中の着信が復帰後に処理されるかを1通で確認。

- [ ] **Step 5: 最終コミットとブランチ完了**

```bash
git add -A && git commit -m "test: E2E確認メモ" || true
```

finishing-a-development-branch スキルで main へのマージ方針を決める。

---

## 動作確認まとめ(各タスクの受け入れ基準)

- T1: `pip freeze` 後、flask/google系がrequirements.txtに入る
- T2: `briefing/secretary.py dry` が通り、cron/タスクが新パスを指す
- T3〜T7: `venv/bin/python -m pytest tests/ -v` が全PASS
- T8: 外部から `/health` が `ok`、LINE「検証」がSuccess
- T9: `systemctl --user status` が active、窓を閉じてもWSL稼働、カレンダー書き込み疎通
- T10: LINEから予定・メモ・雑談の3往復が期待通り
