#!/usr/bin/env python3
# hooks/approval_notify_hook.py
"""Claude Code Notification フック。
承認プロンプト発火 → N秒キーボード無応答なら pane を採取して /approval/notify へ POST。

Task 1 スパイクの発見を反映:
- stdin JSON の notification_type == "permission_prompt" の時だけ処理する。
  ("idle_prompt"(ただの入力待ち)では何もせず即 exit → 無駄な sleep プロセスを湧かせない)
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# --- フック入力(JSON)で承認プロンプトだけに絞る ---
raw = sys.stdin.read()
try:
    event = json.loads(raw) if raw.strip() else {}
except json.JSONDecodeError:
    event = {}
if event.get("notification_type") != "permission_prompt":
    sys.exit(0)  # idle_prompt 等は遠隔承認の対象外

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
