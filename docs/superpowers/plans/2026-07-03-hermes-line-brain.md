# LINEの頭脳をHermesに一元化 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LINEに送った予定・メモ・会話を、記憶ありのHermes(Haiku)1体が受けて判断・応答し、予定はGoogleカレンダー/メモはNotionに書き、スイッチ1個でGeminiに戻せる状態にする。

**Architecture:** 既存webhook(受信・署名・返信)はそのまま流用(道B)。webhookの頭脳呼び出しを「スイッチ付き」にして、on時はローカルのHermes api_server(OpenAI互換HTTP・記憶継続)へ委譲。Hermesは自作ツール(既存 calendar_add / notion_memo / calendar_events を line-news-bot の venv へ subprocess して再利用)で予定/メモを読み書きする。

**Tech Stack:** Python 3.12, Flask(既存webhook), requests, pytest+monkeypatch(既存テスト作法), Hermes Agent(`~/.hermes/hermes-agent/`, api_serverプラットフォーム, `tools/registry.py`), Claude Haiku(`claude-haiku-4-5`)。

## Global Constraints

- 頭脳既定は **`claude-haiku-4-5`**、月上限 **¥1000**(既存設定を踏襲、本計画で変更しない)。
- **Geminiを使わない**(AI×AIループ・無料枠焼けを構造的に排除)。
- 記憶セッションIDは固定値 **`line-owner`**。
- api_server は **localhostのみ**。ローカル共有トークンを使う(`API_SERVER_KEY`)。
- 各設定変更前に対象ファイルを `.bak` 退避(既存慣習: `config.yaml.bak.pre-*`)。
- **朝5:30の通達(briefing)・Telegram窓口は一切いじらない。** 変更対象は「LINEに話しかけたときの返信」経路のみ。
- 新規Hermesツールは line-news-bot リポジトリの `hermes_tools/` に置き、`~/.hermes/hermes-agent/tools/` へ symlink(既存 claude-hermes-bridge と同じ流儀)。
- 既存関数シグネチャ(再利用対象、変更しない):
  - `interactive/actions/calendar_add.py`: `add(title, start_iso, end_iso=None, all_day=False) -> str`
  - `interactive/actions/notion_memo.py`: `add(content, tags=None, when_iso=None) -> str`
  - `briefing/calendar_events.py`: `get_calendar_block() -> str`
- ロールバック: `.env` の `HERMES_BRAIN=off` + webhookサービス再起動で即Gemini経路へ復帰。
- テスト実行: `cd ~/line/line-news-bot && venv/bin/python -m pytest tests/ -v`
- コミットは line-news-bot リポジトリ(現在ブランチ main)で行う。コミット末尾に
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` を付ける。

## File Structure(このプランで触るファイル)

- Create: `interactive/hermes_brain.py` — テキスト+セッションIDをHermes api_serverへ渡し応答文字列を返す薄い配線。
- Create: `interactive/actions/cli.py` — Hermesツールから subprocess で呼ぶCLI入口。`.env`を読み、既存action関数へ振り分ける。
- Create: `hermes_tools/calendar_tool.py` — Hermes自作ツール(予定 登録/照会)。cli.pyへsubprocess。registry自己登録。
- Create: `hermes_tools/memo_tool.py` — Hermes自作ツール(メモ追加)。cli.pyへsubprocess。registry自己登録。
- Modify: `interactive/server.py` — `_process()` の頭脳呼び出しをスイッチ化。
- Test: `tests/test_hermes_brain.py`, `tests/test_actions_cli.py`, `tests/test_server_hermes_switch.py`
- Config(リポジトリ外・手順のみ): `~/.hermes/.env`(api_server有効化), `~/.hermes/config.yaml`(toolset有効化)

---

### Task 1: Hermes api_server を有効化して疎通確認

Hermesに「HTTPで話しかける窓口」を開ける。単体で応答すればHermesの頭脳が呼べる状態。

**Files:**
- Modify: `~/.hermes/.env`(環境変数を追記)
- Backup: `~/.hermes/.env` → `~/.hermes/.env.bak.pre-apiserver`

**Interfaces:**
- Produces: `http://localhost:8642/v1/chat/completions` が Bearer トークン付きPOSTに応答する状態。以降 Task 2 が利用。

- [ ] **Step 1: `.env` を退避**

```bash
cp ~/.hermes/.env ~/.hermes/.env.bak.pre-apiserver
```

- [ ] **Step 2: api_server を有効化する環境変数を追記**

`~/.hermes/.env` に以下を追記(トークンは任意の長い乱数。例は置換すること):

```
API_SERVER_ENABLED=true
API_SERVER_KEY=REPLACE_WITH_LONG_RANDOM_TOKEN
API_SERVER_PORT=8642
API_SERVER_HOST=127.0.0.1
```

トークン生成の一例: `python3 -c "import secrets;print(secrets.token_urlsafe(32))"`。chmod 600 を維持: `chmod 600 ~/.hermes/.env`

- [ ] **Step 3: gateway を再起動**

```bash
systemctl --user restart hermes-gateway
sleep 3
systemctl --user status hermes-gateway --no-pager | head -5
```

Expected: `Active: active (running)`

- [ ] **Step 4: 疎通確認(curl)**

`<TOKEN>` は Step 2 の値に置換:

```bash
curl -s -X POST http://localhost:8642/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "X-Hermes-Session-Id: line-owner" \
  -d '{"model":"hermes-agent","messages":[{"role":"user","content":"テスト。ひとことで返して"}]}'
```

Expected: JSONが返り、`choices[0].message.content` に日本語の短い返答が入る。401なら `Authorization` を確認。接続拒否なら `journalctl --user -u hermes-gateway -n 50 --no-pager` でapi_server起動ログを確認。

- [ ] **Step 5: 疎通できた事実を記録(コミットは無し=設定のみ)**

`~/line/line-news-bot/docs/superpowers/plans/2026-07-03-hermes-line-brain.md` のこのTaskにチェックを入れる。`.env`はgit管理外なのでコミット対象なし。

---

### Task 2: Hermes頭脳への配線 `hermes_brain.py`

LINEのテキストをHermes api_serverへ渡し、応答文字列を返す薄いモジュール。失敗しても例外を出さず定型文を返す。

**Files:**
- Create: `interactive/hermes_brain.py`
- Test: `tests/test_hermes_brain.py`

**Interfaces:**
- Produces: `ask(text: str, session_id: str = "line-owner") -> str` — 常に文字列を返す(例外を投げない)。Task 3 が利用。

- [ ] **Step 1: 失敗テストを書く**

`tests/test_hermes_brain.py`:

```python
import interactive.hermes_brain as hb


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_ask_returns_content(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _Resp({"choices": [{"message": {"content": "やあ、了解！"}}]})

    monkeypatch.setattr(hb.requests, "post", fake_post)
    out = hb.ask("こんにちは", "line-owner")
    assert out == "やあ、了解！"
    assert captured["headers"]["X-Hermes-Session-Id"] == "line-owner"
    assert captured["json"]["messages"][0]["content"] == "こんにちは"


def test_ask_on_error_returns_safe_message(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(hb.requests, "post", boom)
    out = hb.ask("こんにちは", "line-owner")
    assert "調子が悪い" in out
```

- [ ] **Step 2: 失敗を確認**

Run: `cd ~/line/line-news-bot && venv/bin/python -m pytest tests/test_hermes_brain.py -v`
Expected: FAIL(`ModuleNotFoundError: interactive.hermes_brain`)

- [ ] **Step 3: 最小実装**

`interactive/hermes_brain.py`:

```python
#!/usr/bin/env python3
"""LINEのテキストをHermes api_server(ローカル)へ渡し、応答文字列を返す薄い配線。

失敗しても例外を出さず安全な定型文を返す(LINEが無反応にならないように)。
"""
import os
import requests

_SAFE = "ごめん、いま調子が悪いみたい。もう一回送ってくれる?"


def ask(text: str, session_id: str = "line-owner") -> str:
    url = os.environ.get("HERMES_API_URL", "http://localhost:8642/v1/chat/completions")
    key = os.environ.get("HERMES_API_KEY", "")
    headers = {"Content-Type": "application/json", "X-Hermes-Session-Id": session_id}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = {"model": "hermes-agent", "messages": [{"role": "user", "content": text}]}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=180)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        return (content or "").strip() or "(からっぽの返事だったよ)"
    except Exception as e:
        print(f"[ERROR] hermes_brain: {e}")
        return _SAFE
```

- [ ] **Step 4: テスト成功を確認**

Run: `cd ~/line/line-news-bot && venv/bin/python -m pytest tests/test_hermes_brain.py -v`
Expected: PASS(2件)

- [ ] **Step 5: コミット**

```bash
cd ~/line/line-news-bot
git add interactive/hermes_brain.py tests/test_hermes_brain.py
git commit -m "feat: Hermes api_serverへの配線 hermes_brain.ask を追加

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: server.py にスイッチを入れる

`HERMES_BRAIN=on` のとき Hermes、それ以外は既存 Gemini経路(`dispatch.handle`)。ロールバックの要。

**Files:**
- Modify: `interactive/server.py`(`_process` 関数のみ)
- Test: `tests/test_server_hermes_switch.py`

**Interfaces:**
- Consumes: `hermes_brain.ask(text, session_id) -> str`(Task 2)
- Produces: 環境変数 `HERMES_BRAIN` による経路切替。既存 `dispatch.handle` 経路は温存。

- [ ] **Step 1: 失敗テストを書く**

`tests/test_server_hermes_switch.py`:

```python
import interactive.server as server


def test_process_uses_hermes_when_on(monkeypatch):
    monkeypatch.setenv("HERMES_BRAIN", "on")
    sent = {}
    monkeypatch.setattr(server, "hermes_brain",
                        type("M", (), {"ask": staticmethod(lambda t, sid="line-owner": f"H:{t}")}))
    monkeypatch.setattr(server.line_client, "reply", lambda rt, msg: sent.setdefault("msg", msg))
    server._process("やあ", "RT", "2026-07-03T10:00:00+09:00")
    assert sent["msg"] == "H:やあ"


def test_process_uses_gemini_when_off(monkeypatch):
    monkeypatch.setenv("HERMES_BRAIN", "off")
    sent = {}
    monkeypatch.setattr(server.dispatch, "handle", lambda t, n: f"G:{t}")
    monkeypatch.setattr(server.line_client, "reply", lambda rt, msg: sent.setdefault("msg", msg))
    server._process("やあ", "RT", "2026-07-03T10:00:00+09:00")
    assert sent["msg"] == "G:やあ"
```

- [ ] **Step 2: 失敗を確認**

Run: `cd ~/line/line-news-bot && venv/bin/python -m pytest tests/test_server_hermes_switch.py -v`
Expected: FAIL(`test_process_uses_hermes_when_on` で `server.hermes_brain` 属性が無い / 経路が分岐しない)

- [ ] **Step 3: 実装(server.py を編集)**

`interactive/server.py` の先頭 import 群に追加:

```python
from interactive import hermes_brain
```

`_process` を次に置き換え:

```python
def _process(text: str, reply_token: str, now_iso: str) -> None:
    if os.environ.get("HERMES_BRAIN", "").lower() in ("on", "1", "true"):
        msg = hermes_brain.ask(text, "line-owner")
    else:
        msg = dispatch.handle(text, now_iso)
    line_client.reply(reply_token, msg)
```

(`os` は既存importにあり。無ければ `import os` を追加)

- [ ] **Step 4: テスト成功を確認(既存server testも回帰確認)**

Run: `cd ~/line/line-news-bot && venv/bin/python -m pytest tests/test_server_hermes_switch.py tests/test_server.py -v`
Expected: 新規2件 PASS、既存 test_server.py も全PASS(HERMES_BRAIN未設定=off既定なのでGemini経路のまま)

- [ ] **Step 5: コミット**

```bash
cd ~/line/line-news-bot
git add interactive/server.py tests/test_server_hermes_switch.py
git commit -m "feat: server._process にHERMES_BRAINスイッチを追加(既定off=Gemini)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: actions のCLI入口 `interactive/actions/cli.py`

Hermes(別venv/別プロセス)から既存action関数を呼べるよう、`.env`を読み込む薄いCLIを用意。認証情報は line-news-bot 側に留まる。

**Files:**
- Create: `interactive/actions/cli.py`
- Test: `tests/test_actions_cli.py`

**Interfaces:**
- Produces: `main(argv: list[str]) -> dict` と、`python -m interactive.actions.cli <cmd> '<json>'` のCLI。
  - `<cmd>` = `calendar_add` | `memo_add` | `calendar_read`
  - 出力: 最終行にJSON(`{"ok": true, ...}` / `{"ok": false, "error": "..."}`)
  - Task 5, 6 が subprocess で利用。

- [ ] **Step 1: 失敗テストを書く**

`tests/test_actions_cli.py`:

```python
from interactive.actions import cli


def test_calendar_add_dispatch(monkeypatch):
    monkeypatch.setattr(cli, "_calendar_add",
                        lambda **k: "https://cal/x")
    out = cli.main(["cli", "calendar_add",
                    '{"title":"歯医者","start":"2026-07-04T15:00:00+09:00"}'])
    assert out["ok"] is True
    assert out["link"] == "https://cal/x"


def test_memo_add_dispatch(monkeypatch):
    monkeypatch.setattr(cli, "_memo_add", lambda **k: "https://notion/x")
    out = cli.main(["cli", "memo_add", '{"content":"牛乳を買う"}'])
    assert out["ok"] is True
    assert out["url"] == "https://notion/x"


def test_calendar_read_dispatch(monkeypatch):
    monkeypatch.setattr(cli, "_calendar_read", lambda: "・7/4 歯医者 15:00")
    out = cli.main(["cli", "calendar_read"])
    assert out["ok"] is True
    assert "歯医者" in out["block"]


def test_unknown_command():
    out = cli.main(["cli", "nope"])
    assert out["ok"] is False
    assert "unknown" in out["error"]
```

- [ ] **Step 2: 失敗を確認**

Run: `cd ~/line/line-news-bot && venv/bin/python -m pytest tests/test_actions_cli.py -v`
Expected: FAIL(`ModuleNotFoundError: interactive.actions.cli`)

- [ ] **Step 3: 実装**

`interactive/actions/cli.py`:

```python
#!/usr/bin/env python3
"""Hermesツールから subprocess で呼ぶCLI入口。

.env を読み込み、既存の action 関数へ振り分ける。認証情報は line-news-bot 側に留める。
使い方: python -m interactive.actions.cli <cmd> '<json>'
  cmd: calendar_add | memo_add | calendar_read
"""
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env")


def _calendar_add(**kwargs) -> str:
    from interactive.actions import calendar_add
    return calendar_add.add(
        title=kwargs["title"], start_iso=kwargs["start"],
        end_iso=kwargs.get("end"), all_day=kwargs.get("all_day", False),
    )


def _memo_add(**kwargs) -> str:
    from interactive.actions import notion_memo
    return notion_memo.add(
        content=kwargs["content"], tags=kwargs.get("tags"),
        when_iso=kwargs.get("when"),
    )


def _calendar_read() -> str:
    from briefing import calendar_events
    return calendar_events.get_calendar_block()


def main(argv: list) -> dict:
    if len(argv) < 2:
        return {"ok": False, "error": "no command"}
    cmd = argv[1]
    payload = {}
    if len(argv) >= 3 and argv[2].strip():
        payload = json.loads(argv[2])
    if cmd == "calendar_add":
        return {"ok": True, "link": _calendar_add(**payload)}
    if cmd == "memo_add":
        return {"ok": True, "url": _memo_add(**payload)}
    if cmd == "calendar_read":
        return {"ok": True, "block": _calendar_read()}
    return {"ok": False, "error": f"unknown command: {cmd}"}


if __name__ == "__main__":
    try:
        print(json.dumps(main(sys.argv), ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)
```

- [ ] **Step 4: テスト成功を確認**

Run: `cd ~/line/line-news-bot && venv/bin/python -m pytest tests/test_actions_cli.py -v`
Expected: PASS(4件)

- [ ] **Step 5: 実物で1回だけ読み取りを確認(書き込みはしない)**

Run: `cd ~/line/line-news-bot && venv/bin/python -m interactive.actions.cli calendar_read`
Expected: 最終行に `{"ok": true, "block": "..."}`。カレンダーの内容が入る。エラーなら `.env` の `CALENDAR_ICAL_URL` を確認。

- [ ] **Step 6: コミット**

```bash
cd ~/line/line-news-bot
git add interactive/actions/cli.py tests/test_actions_cli.py
git commit -m "feat: Hermesツール用のaction CLI入口 cli.py を追加

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Hermes 予定ツール `hermes_tools/calendar_tool.py`

Hermesが予定を「登録/照会」できる自作ツール。cli.py へ subprocess し、registry に自己登録。

**Files:**
- Create: `hermes_tools/calendar_tool.py`
- Test: `tests/test_calendar_tool.py`
- Symlink(手順): `~/.hermes/hermes-agent/tools/calendar_tool.py` → 本ファイル

**Interfaces:**
- Consumes: `interactive.actions.cli` の CLI(Task 4)
- Produces: Hermesツール `calendar_add`(title, start, end?, all_day?)と `calendar_read`()。toolset名 `line_secretary`。

- [ ] **Step 1: 失敗テストを書く**

`tests/test_calendar_tool.py`:

```python
import json
import hermes_tools.calendar_tool as ct


def test_calendar_add_ok(monkeypatch):
    monkeypatch.setattr(ct, "_run",
                        lambda cmd, payload: {"ok": True, "link": "https://cal/x"})
    out = json.loads(ct.calendar_add("歯医者", "2026-07-04T15:00:00+09:00"))
    assert out["ok"] is True and out["link"] == "https://cal/x"


def test_calendar_read_ok(monkeypatch):
    monkeypatch.setattr(ct, "_run",
                        lambda cmd, payload: {"ok": True, "block": "・7/4 歯医者"})
    out = json.loads(ct.calendar_read())
    assert "歯医者" in out["block"]
```

- [ ] **Step 2: 失敗を確認**

Run: `cd ~/line/line-news-bot && venv/bin/python -m pytest tests/test_calendar_tool.py -v`
Expected: FAIL(`ModuleNotFoundError: hermes_tools.calendar_tool`)

- [ ] **Step 3: 実装**

まず `hermes_tools/__init__.py` を空で作成(パッケージ化):

```bash
mkdir -p ~/line/line-news-bot/hermes_tools && touch ~/line/line-news-bot/hermes_tools/__init__.py
```

`hermes_tools/calendar_tool.py`:

```python
#!/usr/bin/env python3
"""Hermes自作ツール: Googleカレンダーの予定 登録/照会。

line-news-bot の venv/env へ subprocess し、既存 action を再利用する
(認証情報を Hermes 側に持ち込まないため)。
"""
import os
import json
import subprocess

_LNB = os.path.expanduser("~/line/line-news-bot")
_PY = os.path.join(_LNB, "venv/bin/python")


def _run(cmd: str, payload: dict) -> dict:
    try:
        proc = subprocess.run(
            [_PY, "-m", "interactive.actions.cli", cmd, json.dumps(payload, ensure_ascii=False)],
            cwd=_LNB, capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            return {"ok": False, "error": (proc.stderr or proc.stdout).strip()[:300]}
        last = proc.stdout.strip().splitlines()[-1]
        return json.loads(last)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def calendar_add(title: str, start: str, end: str = None, all_day: bool = False) -> str:
    payload = {"title": title, "start": start, "end": end, "all_day": all_day}
    return json.dumps(_run("calendar_add", payload), ensure_ascii=False)


def calendar_read() -> str:
    return json.dumps(_run("calendar_read", {}), ensure_ascii=False)


CALENDAR_ADD_SCHEMA = {
    "description": (
        "ユーザーのGoogleカレンダーに予定を登録する。予定名(title)は発話をそのまま写さず"
        "簡潔にまとめる。start/endはISO8601(例 2026-07-04T15:00:00+09:00)。"
        "終日なら all_day=true。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "簡潔な予定名"},
            "start": {"type": "string", "description": "開始 ISO8601(+09:00)"},
            "end": {"type": "string", "description": "終了 ISO8601(任意)"},
            "all_day": {"type": "boolean", "description": "終日ならtrue"},
        },
        "required": ["title", "start"],
    },
}

CALENDAR_READ_SCHEMA = {
    "description": "ユーザーの直近のカレンダー予定を読み取り、一覧テキストを返す。「予定あったっけ」等の照会に使う。",
    "parameters": {"type": "object", "properties": {}},
}

try:
    from tools import registry

    registry.register(
        name="calendar_add",
        toolset="line_secretary",
        schema=CALENDAR_ADD_SCHEMA,
        handler=lambda args, **kw: calendar_add(
            args.get("title", ""), args.get("start", ""),
            args.get("end"), args.get("all_day", False),
        ),
        emoji="📅",
    )
    registry.register(
        name="calendar_read",
        toolset="line_secretary",
        schema=CALENDAR_READ_SCHEMA,
        handler=lambda args, **kw: calendar_read(),
        emoji="📅",
    )
except Exception:
    pass
```

- [ ] **Step 4: テスト成功を確認**

Run: `cd ~/line/line-news-bot && venv/bin/python -m pytest tests/test_calendar_tool.py -v`
Expected: PASS(2件)

- [ ] **Step 5: コミット**

```bash
cd ~/line/line-news-bot
git add hermes_tools/__init__.py hermes_tools/calendar_tool.py tests/test_calendar_tool.py
git commit -m "feat: Hermes予定ツール calendar_tool を追加(cli経由でGoogleカレンダー)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Hermes メモツール `hermes_tools/memo_tool.py`

Hermesがメモを追加できる自作ツール。calendar_tool と同じ流儀。

**Files:**
- Create: `hermes_tools/memo_tool.py`
- Test: `tests/test_memo_tool.py`

**Interfaces:**
- Consumes: `interactive.actions.cli`(Task 4)、`hermes_tools.calendar_tool._run` と同型の subprocess ヘルパ(本ファイルに複製せず import して再利用)
- Produces: Hermesツール `memo_add`(content, tags?, when?)。toolset名 `line_secretary`。

- [ ] **Step 1: 失敗テストを書く**

`tests/test_memo_tool.py`:

```python
import json
import hermes_tools.memo_tool as mt


def test_memo_add_ok(monkeypatch):
    monkeypatch.setattr(mt, "_run",
                        lambda cmd, payload: {"ok": True, "url": "https://notion/x"})
    out = json.loads(mt.memo_add("牛乳を買う", tags=["買い物"]))
    assert out["ok"] is True and out["url"] == "https://notion/x"
```

- [ ] **Step 2: 失敗を確認**

Run: `cd ~/line/line-news-bot && venv/bin/python -m pytest tests/test_memo_tool.py -v`
Expected: FAIL(`ModuleNotFoundError: hermes_tools.memo_tool`)

- [ ] **Step 3: 実装**

`hermes_tools/memo_tool.py`:

```python
#!/usr/bin/env python3
"""Hermes自作ツール: Notionにメモを追加。cli経由で既存 notion_memo を再利用。"""
import json

from hermes_tools.calendar_tool import _run  # subprocessヘルパを再利用(DRY)


def memo_add(content: str, tags: list = None, when: str = None) -> str:
    payload = {"content": content, "tags": tags, "when": when}
    return json.dumps(_run("memo_add", payload), ensure_ascii=False)


MEMO_ADD_SCHEMA = {
    "description": "ユーザーのNotionメモにメモを追加する。content必須。tagsは任意の文字列配列。",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "メモ本文"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "タグ(任意)"},
            "when": {"type": "string", "description": "日付 ISO8601(任意)"},
        },
        "required": ["content"],
    },
}

try:
    from tools import registry

    registry.register(
        name="memo_add",
        toolset="line_secretary",
        schema=MEMO_ADD_SCHEMA,
        handler=lambda args, **kw: memo_add(
            args.get("content", ""), args.get("tags"), args.get("when"),
        ),
        emoji="📝",
    )
except Exception:
    pass
```

注: `from hermes_tools.calendar_tool import _run` は line-news-bot リポジトリ内での import。Hermes の tools/ には両ファイルを symlink する(Task 7)。symlink 先でも `hermes_tools` パッケージとして解決できるよう、Task 7 で symlink 方式(ディレクトリごと)を用いる。

- [ ] **Step 4: テスト成功を確認**

Run: `cd ~/line/line-news-bot && venv/bin/python -m pytest tests/test_memo_tool.py -v`
Expected: PASS(1件)

- [ ] **Step 5: コミット**

```bash
cd ~/line/line-news-bot
git add hermes_tools/memo_tool.py tests/test_memo_tool.py
git commit -m "feat: Hermesメモツール memo_add を追加(cli経由でNotion)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Hermesにツールを登録(symlink + toolset有効化 + 再起動)

自作ツールをHermesに認識させ、api_server(=LINE頭脳)で使える状態にする。慎重ゾーン。

**Files:**
- Backup: `~/.hermes/config.yaml` → `~/.hermes/config.yaml.bak.pre-linesecretary`
- Symlink: `~/.hermes/hermes-agent/tools/hermes_tools` → `~/line/line-news-bot/hermes_tools`
- Modify: `~/.hermes/config.yaml`(`platform_toolsets` に api_server 用 `line_secretary` を追加)

**Interfaces:**
- Consumes: Task 5, 6 のツールファイル
- Produces: Hermes(api_server経由)で `calendar_add` / `calendar_read` / `memo_add` が呼べる状態。

- [ ] **Step 1: config退避**

```bash
cp ~/.hermes/config.yaml ~/.hermes/config.yaml.bak.pre-linesecretary
```

- [ ] **Step 2: ツールをディレクトリごと symlink**

Hermesがロードするのは `~/.hermes/hermes-agent/tools/` 配下。`hermes_tools` パッケージとして解決させるため、ディレクトリを symlink:

```bash
ln -sfn ~/line/line-news-bot/hermes_tools ~/.hermes/hermes-agent/tools/hermes_tools
ls -l ~/.hermes/hermes-agent/tools/hermes_tools
```

Expected: symlink が張られ、`calendar_tool.py`/`memo_tool.py`/`__init__.py` が見える。

- [ ] **Step 3: ツールのロード確認(登録が走るか静的検査)**

自己登録の `try/except` が握りつぶすため、まず import 単体でエラーが無いか確認:

```bash
~/.hermes/hermes-agent/venv/bin/python -c "import sys; sys.path.insert(0,'/home/yuta/.hermes/hermes-agent'); from tools.hermes_tools import calendar_tool, memo_tool; print('import ok')"
```

Expected: `import ok`(registry未解決でも except で通る)。ImportError が出たらパスを見直す。

- [ ] **Step 4: `config.yaml` の `platform_toolsets` に api_server を追加**

`platform_toolsets:` セクションに次を追記(既存 telegram 等と同階層):

```yaml
platform_toolsets:
  api_server:
  - clarify
  - memory
  - line_secretary
```

(`memory` はHermesの記憶ツール。`line_secretary` が本計画の自作toolset。既存の他プラットフォーム項目は変更しない)

- [ ] **Step 5: gateway再起動**

```bash
systemctl --user restart hermes-gateway
sleep 3
systemctl --user status hermes-gateway --no-pager | head -5
```

Expected: `active (running)`。落ちる場合は `journalctl --user -u hermes-gateway -n 60 --no-pager` を見て、config.yaml のインデント誤りを疑う(退避から復元して再試行)。

- [ ] **Step 6: api_server経由でツールが見えるか実地確認(読み取りのみ)**

`<TOKEN>` を置換:

```bash
curl -s -X POST http://localhost:8642/v1/chat/completions \
  -H "Content-Type: application/json" -H "Authorization: Bearer <TOKEN>" \
  -H "X-Hermes-Session-Id: line-owner" \
  -d '{"model":"hermes-agent","messages":[{"role":"user","content":"私の直近の予定を教えて"}]}'
```

Expected: Hermesが `calendar_read` を使い、カレンダー内容を反映した返答を返す。ツール不認識なら Step 4 の toolset 設定と再起動を再確認。

- [ ] **Step 7: 設定内容を記録(symlink/configはgit外。プランにチェック)**

このTaskのチェックを入れる。設定変更のためコミット対象コードは無し。

---

### Task 8: 実機カットオーバー検証 + ロールバック確認

本番LINEでHermes経路を有効化し、受け入れ基準を満たすか確認。最後にロールバックが効くことも確認。

**Files:**
- Modify(手順): `~/line/line-news-bot/.env`(`HERMES_BRAIN=on`, `HERMES_API_URL`, `HERMES_API_KEY`)
- webhookサービス再起動

**Interfaces:**
- Consumes: Task 1–7 の全成果
- Produces: LINEでHermesと会話でき、予定/メモが実データに反映される状態。

- [ ] **Step 1: 切替前ベースライン(退行チェック)**

Run: `cd ~/line/line-news-bot && venv/bin/python -m pytest tests/ -v`
Expected: 全PASS(新規+既存)。

- [ ] **Step 2: webhook の .env に接続情報を設定**

`~/line/line-news-bot/.env` に追記(`<TOKEN>` は Task 1 の `API_SERVER_KEY` と同値):

```
HERMES_BRAIN=on
HERMES_API_URL=http://localhost:8642/v1/chat/completions
HERMES_API_KEY=<TOKEN>
```

- [ ] **Step 3: webhookサービスを再起動**

```bash
systemctl --user restart secretary-webhook 2>/dev/null || \
  { echo "サービス名を確認:"; systemctl --user list-units | grep -i webhook; }
```

(サービス名は `interactive/secretary-webhook.service` 参照。常駐方法が異なる場合は該当プロセスを再起動)

- [ ] **Step 4: 実機 会話テスト(LINEから)**

LINEで「テスト。ひとことで返して」と送る。
Expected: Hermesが短く返信する(Geminiの定型ではない)。返らない場合は webhook ログと `hermes_brain` の `[ERROR]` を確認。

- [ ] **Step 5: 実機 予定登録テスト**

LINEで「明日15時に歯医者、入れといて」と送る。
Expected: (1) Hermesが登録した旨を返す (2) **スマホのGoogleカレンダー**に「歯医者」相当の予定が15:00で入る(発話まるごとコピペでない簡潔な予定名)。

- [ ] **Step 6: 実機 予定照会テスト**

LINEで「来週なんか予定あったっけ?」と送る。
Expected: Hermesがカレンダーを読んで予定を答える。

- [ ] **Step 7: 実機 メモテスト**

LINEで「牛乳を買うってメモしといて」と送る。
Expected: (1) Hermesが保存した旨を返す (2) **Notion**のメモDBに該当メモが入る。

- [ ] **Step 8: 記憶テスト**

LINEで「さっきの歯医者、何時だっけ?」と送る。
Expected: 直前の文脈を踏まえて答える(セッション記憶が効いている)。

- [ ] **Step 9: 朝の通達 無傷確認**

`briefing` のcron/サービスに変更を加えていないことを確認:

```bash
crontab -l 2>/dev/null | grep -i secretary; systemctl --user list-timers 2>/dev/null | grep -i brief
```

Expected: 既存の通達設定が変更されていない。翌朝5:30に通常どおり届く(または `venv/bin/python briefing/secretary.py dry` で内容生成が壊れていないか確認)。

- [ ] **Step 10: ロールバック確認**

```bash
# .env の HERMES_BRAIN を off にして再起動
sed -i 's/^HERMES_BRAIN=on/HERMES_BRAIN=off/' ~/line/line-news-bot/.env
systemctl --user restart secretary-webhook 2>/dev/null || true
```

LINEで「牛乳メモして」と送る。
Expected: **既存Gemini経路**の挙動(📝定型)に戻る。確認後、本運用するなら `HERMES_BRAIN=on` に戻して再起動。

- [ ] **Step 11: 検証結果をHANDOFF等に記録**

`~/line/line-news-bot/HANDOFF.md` に、有効化状態・ロールバック手順・残課題(画像/音声入力は将来スコープ)を追記してコミット:

```bash
cd ~/line/line-news-bot
git add HANDOFF.md
git commit -m "docs: LINE頭脳のHermes一元化 稼働記録とロールバック手順

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 完成の定義(Definition of Done)

- LINEに送った**会話・予定・メモ**がHermes(Haiku)1体で処理され、予定はGoogleカレンダー、メモはNotionに反映される。
- 「予定あったっけ」にHermesがカレンダーを読んで答える。会話は記憶が継続する。
- `HERMES_BRAIN=off` + 再起動で**即Geminiに戻せる**ことを確認済み。
- **朝5:30の通達・Telegram窓口は無傷**。
- 全ユニットテストがGREEN。
