#!/usr/bin/env python3
"""LINE秘書ブリーフィング 司令塔。
朝5:30に カレンダー予定 + 天気(2地点) + 今朝のニュース1件 + 本日の一語 を
フランクな秘書口調で1通にまとめてLINE送信する。

使い方:
  python3 secretary.py        # 本番送信（当日1回まで）
  python3 secretary.py test   # 重複防止を無視して即送信
  python3 secretary.py dry    # 送信せず内容をstdout表示
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
STATE_FILE = DATA_DIR / "sent_state.json"

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


def _greeting() -> str:
    now = datetime.now(JST)
    wd = WEEKDAY_JP[now.weekday()]
    return f"おはよう、渡辺さん。{now.month}月{now.day}日（{wd}）の朝の通達だよ。"


def build_briefing() -> str:
    from calendar_events import get_calendar_block
    from weather import get_weather_block
    from news_headline import get_news_block
    from daily_word import get_word_block

    blocks = [_greeting()]

    # 各ブロックは独立。失敗しても他は出す。
    try:
        blocks.append(get_calendar_block())
    except Exception as e:
        print(f"[ERROR] calendar: {e}")

    w = None
    try:
        w = get_weather_block()
    except Exception as e:
        print(f"[ERROR] weather: {e}")
    if w:
        blocks.append(w)

    n = None
    try:
        n = get_news_block()
    except Exception as e:
        print(f"[ERROR] news: {e}")
    if n:
        blocks.append(n)

    wd = None
    try:
        wd = get_word_block()
    except Exception as e:
        print(f"[ERROR] word: {e}")
    if wd:
        blocks.append(wd)

    blocks.append("今日もご安全に。")
    return "\n\n".join(blocks)


def _already_sent_today() -> bool:
    if not STATE_FILE.exists():
        return False
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False
    today = datetime.now(JST).strftime("%Y-%m-%d")
    return state.get("sent_date") == today


def _mark_sent() -> None:
    today = datetime.now(JST).strftime("%Y-%m-%d")
    STATE_FILE.write_text(json.dumps({"sent_date": today}, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"

    if mode == "dry":
        print(build_briefing())
        return

    if mode == "run" and _already_sent_today():
        print(f"[SKIP] 本日は送信済み（{datetime.now(JST):%Y-%m-%d}）")
        return

    from line_send import send_line
    message = build_briefing()
    ok = send_line(message)
    if ok:
        if mode == "run":
            _mark_sent()
        print("✅ 送信完了")
    else:
        print("❌ 送信失敗")
        sys.exit(1)


if __name__ == "__main__":
    main()
