#!/usr/bin/env python3
"""GoogleカレンダーのiCal秘密URLから予定を取得し、
当日 / 1週間後 / 3日後 / 1日後 に該当する予定だけ抽出する。

表示ルール:
  - 当日: 予定があれば一覧。無ければ「本日の予定はございません」。
  - 事前通達(7/3/1日後): 該当する予定があるときだけ行を追加。無ければ何も出さない。
"""
import os
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ICAL_URL = os.environ.get("CALENDAR_ICAL_URL", "").strip()
JST = timezone(timedelta(hours=9))

# 該当日数 → ラベル（当日は先頭、事前通達はその後）
DAY_LABELS = {0: "本日", 1: "明日", 3: "3日後", 7: "1週間後"}
TARGET_DAYS = sorted(DAY_LABELS)  # [0, 1, 3, 7]


def _event_date_and_time(component) -> tuple[date, str]:
    """予定の開始日(JST)と時刻文字列を返す。終日予定は時刻 ''。"""
    dtstart = component.get("DTSTART").dt
    if isinstance(dtstart, datetime):
        if dtstart.tzinfo is None:
            dtstart = dtstart.replace(tzinfo=JST)
        local = dtstart.astimezone(JST)
        return local.date(), local.strftime("%H:%M")
    return dtstart, ""  # date型 = 終日


def get_calendar_block() -> str:
    """整形済みの予定ブロックを返す。"""
    header = "📅 今日の予定"

    if not ICAL_URL:
        return f"{header}\n（カレンダー未設定：.env の CALENDAR_ICAL_URL を入れてね）"

    try:
        import icalendar
        import recurring_ical_events
    except ImportError:
        return f"{header}\n（icalendarライブラリ未導入）"

    try:
        resp = requests.get(ICAL_URL, timeout=20,
                            headers={"User-Agent": "SecretaryBot/1.0"})
        resp.raise_for_status()
        cal = icalendar.Calendar.from_ical(resp.content)
    except Exception as e:
        print(f"[WARN] カレンダー取得失敗: {e}")
        return f"{header}\n（カレンダーを取得できなかったよ）"

    today = datetime.now(JST).date()
    start = today
    end = today + timedelta(days=8)

    try:
        occurrences = recurring_ical_events.of(cal).between(start, end)
    except Exception as e:
        print(f"[WARN] 予定展開失敗: {e}")
        return f"{header}\n（予定の読み取りに失敗したよ）"

    # 対象日にマッチする予定を集める: {days_until: [(time, title), ...]}
    buckets: dict[int, list[tuple[str, str]]] = {d: [] for d in TARGET_DAYS}
    for comp in occurrences:
        try:
            ev_date, ev_time = _event_date_and_time(comp)
        except Exception:
            continue
        days_until = (ev_date - today).days
        if days_until in buckets:
            summary = str(comp.get("SUMMARY", "（無題）")).strip()
            buckets[days_until].append((ev_time, summary))

    lines = [header]

    # 当日
    today_events = sorted(buckets[0])
    if today_events:
        for t, title in today_events:
            prefix = f"{t} " if t else ""
            lines.append(f"・{prefix}{title}（▶本日）")
    else:
        lines.append("・本日の予定はございません")

    # 事前通達（該当があるときだけ）
    for d in (1, 3, 7):
        for t, title in sorted(buckets[d]):
            ev_date = (today + timedelta(days=d)).strftime("%-m/%-d")
            prefix = f"{t} " if t else ""
            lines.append(f"・{ev_date} {prefix}{title}（▶{DAY_LABELS[d]}）")

    return "\n".join(lines)


if __name__ == "__main__":
    print(get_calendar_block())
