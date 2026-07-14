#!/usr/bin/env python3
"""Telegram(Claude Code専用bot @watanabe_claudecode_bot)の返信を承認注入へ転送するポーラー。

LINEの「OK」等テキスト横取り(server._try_answer_approval)のTelegram版。
このbotへ来た「OK」「y」「はい」等の返信を拾い、ローカルの
/approval/answer_text (interactive/server.py) へ転送してtmuxに注入させる。
承認語でない普通の雑談は handled=False で返ってくるので黙って無視する(スパム防止)。

長時間ポーリング(getUpdates timeout=25)のループ本体は薄く、
DISPATCH(handle_update)はネットワークをすべて注入で受け取る純関数寄りの作りにして
ユニットテスト可能にしてある(tests/test_telegram_approval_poller.py)。
"""
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from shared import telegram_client  # noqa: E402

load_dotenv(_ROOT / ".env")

_OFFSET_PATH = _ROOT / "data" / "approvals" / "tg_offset.json"
_SERVER_URL = "http://127.0.0.1:8800/approval/answer_text"
_POLL_TIMEOUT = 25  # Telegram long-polling秒数


def poll_once(offset, *, get=requests.get):
    """getUpdates を1回呼ぶ。戻り値 (new_offset, updates)。
    new_offset は次回問い合わせ用(受け取った最大 update_id + 1)。"""
    token = os.environ.get("CLAUDE_TG_BOT_TOKEN", "")
    resp = get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"offset": offset, "timeout": _POLL_TIMEOUT},
        timeout=_POLL_TIMEOUT + 10,
    )
    data = resp.json()
    updates = data.get("result", []) or []
    new_offset = offset
    for u in updates:
        uid = u.get("update_id")
        if isinstance(uid, int) and uid + 1 > new_offset:
            new_offset = uid + 1
    return new_offset, updates


def _extract(update):
    """update から (text, chat_id) を取り出す。message/edited_message どちらも見る。
    テキストが無ければ (None, None)。"""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None, None
    text = msg.get("text")
    if not text:
        return None, None
    chat_id = (msg.get("chat") or {}).get("id")
    return text, chat_id


def handle_update(update, *, answer, reply, allowed_chat) -> None:
    """1件のTelegram updateを処理する。
    - テキストが無い/取得できない → 無視
    - 許可チャット(allowed_chat)以外 → 無視(なりすまし防止)
    - answer(text) を呼び、handled が True の時だけ reply(message) で結果を返す。
      handled=False(承認待ちが無い/承認語でない)の時は黙って無視し、雑談bot化しない。
    """
    text, chat_id = _extract(update)
    if text is None:
        return
    if str(chat_id) != str(allowed_chat):
        return
    result = answer(text) or {}
    if result.get("handled"):
        reply(result.get("message", ""))


def _load_offset() -> int:
    try:
        data = json.loads(_OFFSET_PATH.read_text(encoding="utf-8"))
        return int(data.get("offset", 0))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return 0


def _save_offset(offset: int) -> None:
    _OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _OFFSET_PATH.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps({"offset": offset}), encoding="utf-8")
    os.replace(tmp, _OFFSET_PATH)  # アトミック置換(approval_store と同じ流儀)


def _answer(text: str) -> dict:
    approval_token = os.environ.get("APPROVAL_TOKEN", "")
    resp = requests.post(
        _SERVER_URL, json={"text": text},
        headers={"X-Approval-Token": approval_token}, timeout=15,
    )
    return resp.json()


def _reply(message: str) -> None:
    # 承認後の「✅ 送信しました」確認は鬱陶しいので既定で送らない。
    # TG_APPROVAL_CONFIRM=1 で復活可能。
    if os.environ.get("TG_APPROVAL_CONFIRM", "0") == "1" and message:
        telegram_client.notify(message)


def run():
    """長時間ポーリングの無限ループ。環境未設定なら黙って終了する(グレースフル)。"""
    bot_token = os.environ.get("CLAUDE_TG_BOT_TOKEN", "")
    chat_id = os.environ.get("CLAUDE_TG_CHAT_ID", "")
    approval_token = os.environ.get("APPROVAL_TOKEN", "")
    if not bot_token or not chat_id or not approval_token:
        print(
            "[telegram_approval_poller] CLAUDE_TG_BOT_TOKEN / CLAUDE_TG_CHAT_ID / "
            "APPROVAL_TOKEN のいずれかが未設定のため起動しません。"
        )
        return

    offset = _load_offset()
    if offset == 0:
        # 初回起動: 溜まっている古い返信(テストの「OK」等)を承認に流さないよう、
        # 現在の最新update_idまでoffsetを進めてバックログを読み飛ばす。
        try:
            offset, _ = poll_once(-1)
            _save_offset(offset)
            print(f"[telegram_approval_poller] primed offset={offset} (skipped backlog)")
        except Exception as e:
            print(f"[telegram_approval_poller] prime failed: {type(e).__name__}")
    print(f"[telegram_approval_poller] start offset={offset}")
    while True:
        try:
            offset, updates = poll_once(offset)
            for u in updates:
                handle_update(u, answer=_answer, reply=_reply, allowed_chat=chat_id)
            if updates:
                _save_offset(offset)
        except Exception as e:
            print(f"[telegram_approval_poller] error: {type(e).__name__}: {e}")
            time.sleep(5)


if __name__ == "__main__":
    run()
