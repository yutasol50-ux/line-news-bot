# Claude Code 遠隔承認 (Watch/iPhoneからyes) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 席を離れている間に出た Claude Code の承認プロンプトを、iPhone/Apple Watch の LINE クイックリプライから遠隔で答え、tmux 経由でセッションに注入する。

**Architecture:** 普段の TUI 承認はそのまま残す。Claude Code は tmux 内で常駐（`cc` ラッパー）。Notification フックが承認プロンプトで発火し、N 秒キーボード無応答なら pane をキャプチャして secretary-webhook の `/approval/notify` へ POST。サーバは pane テキストを解析して選択肢を LINE クイックリプライで push。ユーザーがタップ→ postback が `/webhook` に届き、本人 userId 検証・pane 再検証の上 `tmux send-keys` で注入する。

**Tech Stack:** Python 3 / Flask（既存 secretary-webhook）/ tmux 3.4 / LINE Messaging API（push + quick-reply postback）/ pytest。

## Global Constraints

- 全信頼・一段: 破壊系を含め分類・二段ガードはしない。選択肢キーをそのまま送るだけ。
- 承認注入は **本人 LINE userId (`LINE_USER_ID`) のみ**受け付ける。
- 注入直前に pane を再キャプチャし「まだ承認待ち」を確認できた時のみ `send-keys` する（空振り事故防止）。
- 既存 131 テストを壊さない。新規コードは TDD（テスト先行 RED→GREEN）。
- 新規サーバ endpoint は `/capture` と同じく専用トークン（`APPROVAL_TOKEN`）で認証。未設定なら 503 で閉じる。
- tmux 依存: 注入対象の Claude Code は tmux セッション内で動いていること。
- コード配置は `interactive/` 配下（既存の日記モジュールと同じ場所）。フック/ラッパーは repo 内スクリプト＋`~/.claude` / `~/.local/bin` に設置。

---

### Task 1: スパイク — Notification フックの発火と pane 特定を実機確認

本設計の土台（フックが承認プロンプトで発火し pane を特定できる）を最初に裏取りする。ダメなら
capture-pane ポーリング常駐に切替（アーキ全体は不変、検知トリガのみ差替）。**このタスクは
手動検証で、実際の承認プロンプトの `capture-pane` テキスト実サンプルを採取して Task 2 に渡すのが成果物。**

**Files:**
- Create: `scratch/approval_hook_probe.sh`（一時。stdin と env をログするだけ）
- Create: `docs/superpowers/notes/2026-07-08-approval-hook-findings.md`（採取結果）

- [ ] **Step 1: プローブフックを書く**

```bash
mkdir -p scratch
cat > scratch/approval_hook_probe.sh <<'SH'
#!/usr/bin/env bash
# Notification フックのデバッグ用。stdin(JSON) と関連 env をログに落とすだけ。
LOG="$HOME/line/line-news-bot/scratch/hook_probe.log"
{
  echo "=== $(date -Iseconds) ==="
  echo "TMUX_PANE=$TMUX_PANE"
  echo "TMUX=$TMUX"
  echo "PWD=$PWD"
  echo "--- stdin ---"
  cat
  echo
} >> "$LOG" 2>&1
SH
chmod +x scratch/approval_hook_probe.sh
```

- [ ] **Step 2: フックを一時登録**

`~/.claude/settings.json` の `hooks` に一時追加（検証後に消す）:

```json
"Notification": [
  { "hooks": [ { "type": "command", "command": "/home/yuta/line/line-news-bot/scratch/approval_hook_probe.sh" } ] }
]
```

- [ ] **Step 3: tmux 内で Claude Code を起動し承認プロンプトを発生させる**

```bash
tmux new-session -A -s probe
# セッション内で:  claude
# Claude に「echo hi を bash で実行して」等と頼み、承認プロンプトを出す。
# その状態で別ペインから: tmux capture-pane -p -t probe > scratch/prompt_capture.txt
```

- [ ] **Step 4: 結果を記録して判断**

`scratch/hook_probe.log` を確認し、以下を findings.md に記録:
- Notification フックは承認プロンプトで発火したか（Yes/No）
- stdin JSON の構造（`message` / `session_id` 等のキー）
- `TMUX_PANE` は取れたか
- `scratch/prompt_capture.txt` に**承認プロンプトの実テキスト**を貼る（Task 2 のテスト素材）

判断:
- 発火した → 設計どおりフック方式で進む（Task 8）。
- 発火しない/情報不足 → findings.md に「ポーリング常駐に切替」と明記し、Task 8 を capture-pane
  ポーリング版に読み替える（他タスクは不変）。

- [ ] **Step 5: 一時フックを外す**

`~/.claude/settings.json` から Notification プローブを削除。`scratch/` は commit しない（`.gitignore` 済みでなければ追加）。

- [ ] **Step 6: Commit（findings のみ）**

```bash
git add docs/superpowers/notes/2026-07-08-approval-hook-findings.md
git commit -m "spike(approval): Notificationフック発火とpane特定を実機確認"
```

---

### Task 2: approval_parse — pane テキスト解析（純関数）

**Files:**
- Create: `interactive/approval_parse.py`
- Test: `tests/test_approval_parse.py`

**Interfaces:**
- Produces:
  - `is_prompt(capture_text: str) -> bool` — Claude Code の承認プロンプトが表示中か。
  - `parse(capture_text: str) -> dict | None` — `{"question": str, "choices": [{"key": str, "label": str}]}`。承認プロンプトでなければ `None`。

**Note:** テスト素材は Task 1 の `prompt_capture.txt` 実テキストで最終確定する。以下は Claude Code の
典型フォーマット（番号選択・先頭に `❯`）に基づく初期実装。Task 1 の実サンプルと差異があれば正規表現を合わせる。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_approval_parse.py
from interactive import approval_parse as ap

PROMPT = """\
● Bash(echo hi)
  ⎿  Running…

Do you want to proceed?
❯ 1. Yes
  2. Yes, and don't ask again for echo commands
  3. No, and tell Claude what to do differently (esc)
"""

IDLE = """\
✻ Churned for 59s
───────────────
❯
  ? for shortcuts
"""


def test_is_prompt_true_on_permission_prompt():
    assert ap.is_prompt(PROMPT) is True


def test_is_prompt_false_on_idle():
    assert ap.is_prompt(IDLE) is False


def test_parse_extracts_question_and_choices():
    r = ap.parse(PROMPT)
    assert r["question"] == "Do you want to proceed?"
    keys = [c["key"] for c in r["choices"]]
    assert keys == ["1", "2", "3"]
    assert r["choices"][0]["label"].startswith("Yes")
    assert "ask again" in r["choices"][1]["label"]


def test_parse_returns_none_on_idle():
    assert ap.parse(IDLE) is None
```

- [ ] **Step 2: RED 確認**

Run: `venv/bin/pytest tests/test_approval_parse.py -v`
Expected: FAIL（`No module named 'interactive.approval_parse'`）

- [ ] **Step 3: 実装**

```python
# interactive/approval_parse.py
"""tmux capture-pane のテキストから Claude Code 承認プロンプトを解析する純関数。"""
import re

# 「❯ 1. Yes」「  2. ...」形式の選択肢行。先頭の ❯ / 空白を許容。
_CHOICE_RE = re.compile(r"^\s*(?:❯\s*)?(\d+)\.\s+(.*\S)\s*$")
# 承認プロンプトの合図(いずれか)。Claude Code の TUI 文言に依存するため複数許容。
_PROMPT_MARKERS = ("Do you want to proceed?", "Do you want to make this edit")


def _lines(text: str) -> list[str]:
    return text.replace("\r", "").split("\n")


def is_prompt(capture_text: str) -> bool:
    """承認プロンプトが表示中か。マーカー文言 + 番号選択肢が2つ以上あれば真。"""
    has_marker = any(m in capture_text for m in _PROMPT_MARKERS)
    n_choices = sum(1 for ln in _lines(capture_text) if _CHOICE_RE.match(ln))
    return has_marker and n_choices >= 2


def parse(capture_text: str):
    """`{"question", "choices":[{"key","label"}]}` or None。"""
    if not is_prompt(capture_text):
        return None
    question = ""
    for m in _PROMPT_MARKERS:
        if m in capture_text:
            question = m
            break
    choices = []
    for ln in _lines(capture_text):
        mo = _CHOICE_RE.match(ln)
        if mo:
            # ラベル末尾の "(esc)" 等の装飾は落とす
            label = re.sub(r"\s*\(esc\)\s*$", "", mo.group(2)).strip()
            choices.append({"key": mo.group(1), "label": label})
    return {"question": question, "choices": choices}
```

- [ ] **Step 4: GREEN 確認**

Run: `venv/bin/pytest tests/test_approval_parse.py -v`
Expected: PASS（4 件）

- [ ] **Step 5: Commit**

```bash
git add interactive/approval_parse.py tests/test_approval_parse.py
git commit -m "feat(approval): pane解析(承認プロンプト検知+選択肢抽出)"
```

---

### Task 3: approval_store — 保留箱（pane 単位・アトミック）

**Files:**
- Create: `interactive/approval_store.py`
- Test: `tests/test_approval_store.py`

**Interfaces:**
- Produces:
  - `register(pane: str, cwd: str, question: str, choices: list[dict], *, now_iso: str, token: str) -> None`
  - `get(token: str) -> dict | None` — 保留エントリ（state=="pending" のみ）。
  - `resolve(token: str) -> None` — state を "done" にする。
  - `pending_panes() -> list[str]` — pending な pane 一覧（多重時の表示用）。
  - ストアパスは `APPROVAL_STORE`（env）> 既定 `data/approvals/pending.json`。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_approval_store.py
import importlib
from interactive import approval_store as store


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE", str(tmp_path / "p.json"))
    importlib.reload(store)
    return store


def test_register_then_get(tmp_path, monkeypatch):
    s = _fresh(tmp_path, monkeypatch)
    s.register("%3", "~/x", "Q?", [{"key": "1", "label": "Yes"}],
               now_iso="2026-07-08T12:00:00+09:00", token="tok1")
    e = s.get("tok1")
    assert e["pane"] == "%3"
    assert e["choices"][0]["key"] == "1"
    assert e["state"] == "pending"


def test_get_missing_returns_none(tmp_path, monkeypatch):
    s = _fresh(tmp_path, monkeypatch)
    assert s.get("nope") is None


def test_resolve_marks_done(tmp_path, monkeypatch):
    s = _fresh(tmp_path, monkeypatch)
    s.register("%3", "~/x", "Q?", [], now_iso="t", token="tok1")
    s.resolve("tok1")
    assert s.get("tok1") is None  # pending でなくなる


def test_pending_panes(tmp_path, monkeypatch):
    s = _fresh(tmp_path, monkeypatch)
    s.register("%1", "~/a", "Q", [], now_iso="t", token="t1")
    s.register("%2", "~/b", "Q", [], now_iso="t", token="t2")
    s.resolve("t1")
    assert s.pending_panes() == ["%2"]
```

- [ ] **Step 2: RED 確認**

Run: `venv/bin/pytest tests/test_approval_store.py -v`
Expected: FAIL（module 無し）

- [ ] **Step 3: 実装**

```python
# interactive/approval_store.py
"""承認保留箱。JSON 1ファイルに token→エントリ。アトミック書き込み。"""
import json
import os
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "approvals" / "pending.json"


def _path() -> Path:
    return Path(os.environ.get("APPROVAL_STORE", str(_DEFAULT)))


def _load() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)  # アトミック置換


def register(pane, cwd, question, choices, *, now_iso, token) -> None:
    data = _load()
    data[token] = {
        "token": token, "pane": pane, "cwd": cwd, "question": question,
        "choices": choices, "created": now_iso, "state": "pending",
    }
    _save(data)


def get(token: str):
    e = _load().get(token)
    if e and e.get("state") == "pending":
        return e
    return None


def resolve(token: str) -> None:
    data = _load()
    if token in data:
        data[token]["state"] = "done"
        _save(data)


def pending_panes() -> list:
    return [e["pane"] for e in _load().values() if e.get("state") == "pending"]
```

- [ ] **Step 4: GREEN 確認**

Run: `venv/bin/pytest tests/test_approval_store.py -v`
Expected: PASS（4 件）

- [ ] **Step 5: Commit**

```bash
git add interactive/approval_store.py tests/test_approval_store.py
git commit -m "feat(approval): 保留箱(pane単位・アトミック保存)"
```

---

### Task 4: line_client.push_quick_reply — クイックリプライ付き push

**Files:**
- Modify: `shared/line_client.py`
- Test: `tests/test_line_quick_reply.py`

**Interfaces:**
- Produces:
  - `push_quick_reply(text: str, items: list[dict]) -> bool` — `items` は `[{"label": str, "data": str}]`。
    各 item を LINE quick-reply の postback アクションに変換して 1 メッセージで push。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_line_quick_reply.py
from unittest.mock import patch, MagicMock
from shared import line_client


def test_push_quick_reply_builds_postback_items():
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        m = MagicMock(); m.status_code = 200; m.text = "ok"
        return m

    with patch("shared.line_client.requests.post", side_effect=fake_post):
        ok = line_client.push_quick_reply(
            "承認して",
            [{"label": "Yes", "data": "approve:tok:1"},
             {"label": "却下", "data": "approve:tok:3"}],
        )
    assert ok is True
    msg = captured["json"]["messages"][0]
    assert msg["text"] == "承認して"
    items = msg["quickReply"]["items"]
    assert items[0]["action"]["type"] == "postback"
    assert items[0]["action"]["label"] == "Yes"
    assert items[0]["action"]["data"] == "approve:tok:1"
    assert items[0]["action"]["displayText"] == "Yes"
    assert len(items) == 2
```

- [ ] **Step 2: RED 確認**

Run: `venv/bin/pytest tests/test_line_quick_reply.py -v`
Expected: FAIL（`push_quick_reply` 無し）

- [ ] **Step 3: 実装（`shared/line_client.py` の末尾に追加）**

```python
def push_quick_reply(text: str, items: list) -> bool:
    """text + クイックリプライ(postback)を1メッセージで push。

    items: [{"label": 表示ラベル, "data": postbackデータ}]。ラベルは20字上限に丸める。
    LINE の quickReply は最大13個。超過分は切り捨て(呼び出し側で警告済みの想定)。
    """
    qr_items = [
        {
            "type": "action",
            "action": {
                "type": "postback",
                "label": it["label"][:20],
                "data": it["data"],
                "displayText": it["label"][:20],
            },
        }
        for it in items[:13]
    ]
    message = {"type": "text", "text": text[:4900], "quickReply": {"items": qr_items}}
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers=_HEADERS,
            json={"to": LINE_USER_ID, "messages": [message]},
            timeout=30,
        )
        if resp.status_code == 200:
            return True
        print(f"[ERROR] quick-reply push失敗: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[ERROR] quick-reply push例外: {e}")
    return False
```

- [ ] **Step 4: GREEN 確認**

Run: `venv/bin/pytest tests/test_line_quick_reply.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shared/line_client.py tests/test_line_quick_reply.py
git commit -m "feat(approval): LINEクイックリプライ(postback)付きpush"
```

---

### Task 5: tmux_inject — capture / send-keys の薄いラッパー

**Files:**
- Create: `interactive/tmux_inject.py`
- Test: `tests/test_tmux_inject.py`

**Interfaces:**
- Produces:
  - `capture(pane: str) -> str` — `tmux capture-pane -p -t <pane>` の標準出力。失敗時は `""`。
  - `send_key(pane: str, key: str) -> bool` — `tmux send-keys -t <pane> <key> Enter`。成功で True。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_tmux_inject.py
from unittest.mock import patch, MagicMock
from interactive import tmux_inject


def test_capture_returns_stdout():
    m = MagicMock(); m.returncode = 0; m.stdout = "PANE TEXT"
    with patch("interactive.tmux_inject.subprocess.run", return_value=m) as run:
        out = tmux_inject.capture("%3")
    assert out == "PANE TEXT"
    args = run.call_args[0][0]
    assert args[:3] == ["tmux", "capture-pane", "-p"]
    assert "%3" in args


def test_send_key_calls_send_keys_with_enter():
    m = MagicMock(); m.returncode = 0
    with patch("interactive.tmux_inject.subprocess.run", return_value=m) as run:
        ok = tmux_inject.send_key("%3", "1")
    assert ok is True
    args = run.call_args[0][0]
    assert args[:2] == ["tmux", "send-keys"]
    assert "%3" in args and "1" in args and "Enter" in args


def test_capture_returns_empty_on_failure():
    m = MagicMock(); m.returncode = 1; m.stdout = ""
    with patch("interactive.tmux_inject.subprocess.run", return_value=m):
        assert tmux_inject.capture("%3") == ""
```

- [ ] **Step 2: RED 確認**

Run: `venv/bin/pytest tests/test_tmux_inject.py -v`
Expected: FAIL（module 無し）

- [ ] **Step 3: 実装**

```python
# interactive/tmux_inject.py
"""tmux capture-pane / send-keys の薄いラッパー(テストでモックしやすいよう分離)。"""
import subprocess


def capture(pane: str) -> str:
    try:
        r = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", pane],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout if r.returncode == 0 else ""
    except Exception as e:
        print(f"[ERROR] tmux capture失敗: {e}")
        return ""


def send_key(pane: str, key: str) -> bool:
    try:
        r = subprocess.run(
            ["tmux", "send-keys", "-t", pane, key, "Enter"],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"[ERROR] tmux send-keys失敗: {e}")
        return False
```

- [ ] **Step 4: GREEN 確認**

Run: `venv/bin/pytest tests/test_tmux_inject.py -v`
Expected: PASS（3 件）

- [ ] **Step 5: Commit**

```bash
git add interactive/tmux_inject.py tests/test_tmux_inject.py
git commit -m "feat(approval): tmux capture/send-keysラッパー"
```

---

### Task 6: /approval/notify エンドポイント — 登録 + クイックリプライ push

**Files:**
- Modify: `interactive/server.py`
- Test: `tests/test_approval_notify.py`

**Interfaces:**
- Consumes: `approval_parse.parse`, `approval_store.register`, `line_client.push_quick_reply`。
- HTTP: `POST /approval/notify`（`X-Approval-Token` 認証）。ボディ JSON:
  `{"pane": str, "cwd": str, "capture": str}`。
  - token 未設定サーバ → 503。token 不一致 → 401。capture が承認プロンプトでない → 204（何もしない）。
  - 承認プロンプト → token 生成 → store.register → push_quick_reply → 200 `{"token": ...}`。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_approval_notify.py
import importlib
from unittest.mock import patch


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_TOKEN", "sekret")
    monkeypatch.setenv("APPROVAL_STORE", str(tmp_path / "p.json"))
    from interactive import server
    importlib.reload(server)
    server.app.config["TESTING"] = True
    return server


PROMPT = "Do you want to proceed?\n❯ 1. Yes\n  2. Yes, and don't ask again\n  3. No (esc)\n"


def test_notify_registers_and_pushes(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    with patch("interactive.server.line_client.push_quick_reply", return_value=True) as push:
        r = server.app.test_client().post(
            "/approval/notify",
            json={"pane": "%3", "cwd": "~/x", "capture": PROMPT},
            headers={"X-Approval-Token": "sekret"},
        )
    assert r.status_code == 200
    tok = r.get_json()["token"]
    from interactive import approval_store
    assert approval_store.get(tok)["pane"] == "%3"
    assert push.called
    # ボタンの data は approve:<token>:<key>
    items = push.call_args[0][1]
    assert items[0]["data"] == f"approve:{tok}:1"


def test_notify_rejects_bad_token(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    r = server.app.test_client().post(
        "/approval/notify", json={"pane": "%3", "cwd": "", "capture": PROMPT},
        headers={"X-Approval-Token": "wrong"})
    assert r.status_code == 401


def test_notify_ignores_non_prompt(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    with patch("interactive.server.line_client.push_quick_reply") as push:
        r = server.app.test_client().post(
            "/approval/notify", json={"pane": "%3", "cwd": "", "capture": "idle\n❯\n"},
            headers={"X-Approval-Token": "sekret"})
    assert r.status_code == 204
    assert not push.called
```

- [ ] **Step 2: RED 確認**

Run: `venv/bin/pytest tests/test_approval_notify.py -v`
Expected: FAIL（route 無し → 404）

- [ ] **Step 3: 実装（`server.py`）**

import 追加（既存 import 群の近くに）:

```python
import secrets
from interactive import approval_parse
from interactive import approval_store
from interactive import tmux_inject
from shared import line_client
```

`/capture` の下あたりに追加:

```python
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
    line_client.push_quick_reply(header, items)
    return {"token": token}, 200
```

- [ ] **Step 4: GREEN 確認**

Run: `venv/bin/pytest tests/test_approval_notify.py -v`
Expected: PASS（3 件）

- [ ] **Step 5: 全体テストで回帰なし確認**

Run: `venv/bin/pytest -q`
Expected: 既存 + 新規すべて PASS

- [ ] **Step 6: Commit**

```bash
git add interactive/server.py tests/test_approval_notify.py
git commit -m "feat(approval): /approval/notify(登録+クイックリプライpush)"
```

---

### Task 7: postback ハンドリング — 本人検証・pane 再検証・注入

**Files:**
- Modify: `interactive/server.py`
- Test: `tests/test_approval_postback.py`

**Interfaces:**
- Consumes: `approval_store.get/resolve`, `tmux_inject.capture/send_key`, `approval_parse.is_prompt`,
  `line_client.push`。
- 追加関数: `handle_postback(data: str, user_id: str) -> None`。
  `/webhook` ループに postback イベント分岐を足して呼ぶ。
- 動作:
  1. `user_id != LINE_USER_ID` → 無視（本人以外）。
  2. data が `approve:<token>:<key>` でなければ無視。
  3. `approval_store.get(token)` が無ければ「もう解決済みでした」を push して終了。
  4. `tmux_inject.capture(pane)` を再取得し `is_prompt` が False（承認待ちでない）→ resolve だけして
     「席で先に答えたようなので送りませんでした」を push。
  5. まだ承認待ち → `send_key(pane, key)` → resolve → 「✅ 送信しました（key. label）」を push。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_approval_postback.py
import importlib
from unittest.mock import patch


def _server(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE", str(tmp_path / "p.json"))
    from interactive import server, approval_store
    importlib.reload(approval_store)
    importlib.reload(server)
    return server, approval_store


PROMPT = "Do you want to proceed?\n❯ 1. Yes\n  2. no\n  3. No (esc)\n"


def test_owner_tap_injects_when_still_pending(tmp_path, monkeypatch):
    server, store = _server(tmp_path, monkeypatch)
    store.register("%3", "~/x", "Q?", [{"key": "1", "label": "Yes"}],
                   now_iso="t", token="tok")
    with patch("interactive.server.line_client.LINE_USER_ID", "OWNER"), \
         patch("interactive.server.tmux_inject.capture", return_value=PROMPT), \
         patch("interactive.server.tmux_inject.send_key", return_value=True) as send, \
         patch("interactive.server.line_client.push", return_value=True):
        server.handle_postback("approve:tok:1", "OWNER")
    send.assert_called_once_with("%3", "1")
    assert store.get("tok") is None  # resolved


def test_non_owner_ignored(tmp_path, monkeypatch):
    server, store = _server(tmp_path, monkeypatch)
    store.register("%3", "~/x", "Q?", [], now_iso="t", token="tok")
    with patch("interactive.server.line_client.LINE_USER_ID", "OWNER"), \
         patch("interactive.server.tmux_inject.send_key") as send:
        server.handle_postback("approve:tok:1", "SOMEONE_ELSE")
    assert not send.called
    assert store.get("tok") is not None  # 手つかず


def test_not_pending_does_not_inject(tmp_path, monkeypatch):
    server, store = _server(tmp_path, monkeypatch)
    store.register("%3", "~/x", "Q?", [], now_iso="t", token="tok")
    with patch("interactive.server.line_client.LINE_USER_ID", "OWNER"), \
         patch("interactive.server.tmux_inject.capture", return_value="idle\n❯\n"), \
         patch("interactive.server.tmux_inject.send_key") as send, \
         patch("interactive.server.line_client.push", return_value=True):
        server.handle_postback("approve:tok:1", "OWNER")
    assert not send.called
    assert store.get("tok") is None  # resolve はする(空振り確定)
```

- [ ] **Step 2: RED 確認**

Run: `venv/bin/pytest tests/test_approval_postback.py -v`
Expected: FAIL（`handle_postback` 無し）

- [ ] **Step 3: 実装（`server.py`）**

`handle_postback` を追加:

```python
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
    entry = approval_store.get(token)
    if entry is None:
        line_client.push("この承認はもう解決済みでした。")
        return
    pane = entry["pane"]
    if not approval_parse.is_prompt(tmux_inject.capture(pane)):
        approval_store.resolve(token)
        line_client.push("席で先に答えたようなので、送りませんでした。")
        return
    ok = tmux_inject.send_key(pane, key)
    approval_store.resolve(token)
    label = next((c["label"] for c in entry["choices"] if c["key"] == key), "")
    line_client.push(f"✅ 送信しました（{key}. {label}）" if ok else "⚠️ 送信に失敗しました。")
```

`/webhook` の `for event in ...` ループ冒頭（`if event.get("type") != "message"` の**前**）に postback 分岐を追加:

```python
        if event.get("type") == "postback":
            event_id = event.get("webhookEventId", "")
            if _seen(event_id):
                continue
            uid = event.get("source", {}).get("userId", "")
            pb = event.get("postback", {}).get("data", "")
            _spawn(lambda d=pb, u=uid: handle_postback(d, u))
            continue
```

- [ ] **Step 4: GREEN 確認**

Run: `venv/bin/pytest tests/test_approval_postback.py -v`
Expected: PASS（3 件）

- [ ] **Step 5: 回帰確認**

Run: `venv/bin/pytest -q`
Expected: すべて PASS

- [ ] **Step 6: Commit**

```bash
git add interactive/server.py tests/test_approval_postback.py
git commit -m "feat(approval): postback注入(本人検証+pane再検証で空振り防止)"
```

---

### Task 8: Notification フック＋`cc` ラッパー（Claude 側グルー）＋手動 E2E

Task 1 が「フック発火 OK」だった前提。NG だった場合は Step 2 を capture-pane ポーリング版に読み替える
（findings.md の判断に従う）。

**Files:**
- Create: `hooks/approval_notify_hook.py`（repo 内。Claude Code の Notification フックが叩く）
- Create: `bin/cc`（repo 内。`~/.local/bin/cc` へ symlink する透過ラッパー）
- Modify: `~/.claude/settings.json`（`hooks.Notification` に登録）
- Modify: `.env`（`APPROVAL_TOKEN` 発行、`APPROVAL_IDLE_SEC` 既定 45）
- Doc: `docs/superpowers/notes/2026-07-08-approval-activation.md`（設置手順）

**Interfaces:**
- Consumes: `POST /approval/notify`（Task 6）, `interactive.approval_parse.is_prompt`, `interactive.tmux_inject.capture`。

- [ ] **Step 1: フックスクリプトを書く**

```python
#!/usr/bin/env python3
# hooks/approval_notify_hook.py
"""Claude Code Notification フック。
承認プロンプト発火→N秒キーボード無応答なら pane を採取して /approval/notify へ POST。"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

sys.stdin.read()  # フック入力(JSON)は今は未使用。読み捨てて後方互換に。
pane = os.environ.get("TMUX_PANE", "")
if not pane:
    sys.exit(0)  # tmux 外(=遠隔不可)なら何もしない

from interactive import approval_parse, tmux_inject  # noqa: E402
import requests  # noqa: E402

idle = int(os.environ.get("APPROVAL_IDLE_SEC", "45"))
time.sleep(idle)

cap = tmux_inject.capture(pane)
if not approval_parse.is_prompt(cap):
    sys.exit(0)  # N秒以内に席で答えた → 何もしない

token = os.environ.get("APPROVAL_TOKEN", "")
if not token:
    sys.exit(0)
try:
    requests.post(
        "http://127.0.0.1:8800/approval/notify",
        headers={"X-Approval-Token": token},
        json={"pane": pane, "cwd": os.getcwd(), "capture": cap},
        timeout=15,
    )
except Exception as e:
    print(f"[approval-hook] POST失敗: {e}", file=sys.stderr)
```

- [ ] **Step 2: `cc` ラッパーを書く**

```bash
#!/usr/bin/env bash
# bin/cc — Claude Code を常駐tmuxセッション内で起動(何回打っても同じ 'claude' に戻る)。
exec tmux new-session -A -s claude "claude ${*}"
```

- [ ] **Step 3: 設置（手動・冪等）**

```bash
chmod +x hooks/approval_notify_hook.py bin/cc
mkdir -p ~/.local/bin && ln -sf "$PWD/bin/cc" ~/.local/bin/cc
# APPROVAL_TOKEN を発行(未設定時のみ)
grep -q '^APPROVAL_TOKEN=' .env || echo "APPROVAL_TOKEN=$(python3 -c 'import secrets;print(secrets.token_hex(16))')" >> .env
grep -q '^APPROVAL_IDLE_SEC=' .env || echo "APPROVAL_IDLE_SEC=45" >> .env
```

`~/.claude/settings.json` の `hooks` に追加（既存 SessionStart は残す）:

```json
"Notification": [
  { "hooks": [ { "type": "command",
    "command": "/home/yuta/line/line-news-bot/venv/bin/python3 /home/yuta/line/line-news-bot/hooks/approval_notify_hook.py" } ] }
]
```

- [ ] **Step 4: webhook サービスを再起動（新コード反映）**

```bash
systemctl --user restart secretary-webhook.service
systemctl --user is-active secretary-webhook.service   # active を確認
```

- [ ] **Step 5: 手動 E2E**

1. `cc` で Claude Code を tmux 内起動。
2. 「`echo hi` を bash で実行して」等で承認プロンプトを出す。**キーボードで答えず 45 秒待つ。**
3. iPhone/Watch の LINE に「🔐 承認待ち … 1. Yes / 2. … / 3. …」が届くのを確認。
4. `1. Yes` をタップ → Claude Code 側で `1` が注入され続行、LINE に「✅ 送信しました（1. Yes）」。
5. 空振り確認: もう一度プロンプトを出し、**先にキーボードで答えてから** LINE のボタンを押し、
   「席で先に答えたようなので送りませんでした」が返る（注入されない）ことを確認。

- [ ] **Step 6: 設置手順を記録して Commit**

```bash
# 手順を docs/superpowers/notes/2026-07-08-approval-activation.md に記す(トークン値は書かない)
git add hooks/approval_notify_hook.py bin/cc docs/superpowers/notes/2026-07-08-approval-activation.md
git commit -m "feat(approval): Notificationフック+ccラッパー+設置手順(E2E確認済)"
```

---

## Self-Review 結果

**Spec coverage:** 通知チャネル(Task4,6)/全信頼一段(Task2 分類なし)/離席フォールバック(Task8 idle sleep)/
tmux 注入(Task5,7)/pane 解析(Task2)/保留箱(Task3)/空振り防止(Task7)/本人限定(Task7)/
フォールバック無害(全 push は例外握り)/前提リスク検証(Task1) — 全項目にタスク対応あり。

**Placeholder scan:** TODO/TBD なし。各コードステップは実コードを掲載。Task1/8 の手動手順は具体化済み。

**Type consistency:** `register(pane,cwd,question,choices,*,now_iso,token)` は Task3/6 で一致。
`get`→pending のみ返す前提を Task6/7 で共有。postback data 形式 `approve:<token>:<key>` は Task6 生成・Task7 解析で一致。
`push_quick_reply(text, items[{label,data}])` は Task4 定義・Task6 使用で一致。
`is_prompt`/`parse`/`capture`/`send_key` の署名は各タスクで一致。
