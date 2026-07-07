#!/usr/bin/env python3
"""20時の日記の声かけ。cronから叩く。

①古い下書きがあれば確定 → ②今日の日記モード開始 → ③「今日どうだった?」をLINE push。
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from interactive import diary_state
from interactive.diary_collector import finalize_timeout, flush
from shared import line_client

_JST = timezone(timedelta(hours=9))
_GREETING = "今日はどうだった?📔 一日を教えて。箇条書きでもいいよ。書き終わったら「終わり」って言ってね。"


def run(*, now_iso=None) -> None:
    now_iso = now_iso or datetime.now(_JST).isoformat(timespec="seconds")
    try:
        flush(now_iso=now_iso)          # 書きかけを保存してから新規開始(消失防止)
    except Exception as e:
        # 保存に失敗したら新規開始しない(書きかけを02:00の刈取りに残す=消さない)
        print(f"[WARN] diary_prompt flush failed, skip start: {e}")
        return
    diary_state.start(now_iso[:10], now=now_iso)
    line_client.push(_GREETING)


def reap(*, now_iso=None) -> None:
    now_iso = now_iso or datetime.now(_JST).isoformat(timespec="seconds")
    try:
        finalize_timeout(now_iso=now_iso)
    except Exception as e:
        print(f"[WARN] diary_prompt reap: {e}")


if __name__ == "__main__":
    import sys
    (reap if len(sys.argv) > 1 and sys.argv[1] == "reap" else run)()
