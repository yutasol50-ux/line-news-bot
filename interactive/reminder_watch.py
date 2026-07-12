#!/usr/bin/env python3
"""リマインダー見張り番。毎分cronで実行し、到来済みの⏰予定をPushcutで鳴らす。

台帳=Googleカレンダーの⏰予定(reminder_add が作る)。この見張りは:
  1. 直近2時間〜今+1分の時間帯の予定を読む
  2. summary が ⏰ で始まる=リマインダー、かつ未配達のものを
  3. Pushcut通知(本文=⏰を剥がした内容)＋既配達フラグ(reminder_store)

completed/snooze は server.py の webhook が reminder_store と予定を操作する。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_MARK = "⏰"
_JST = timezone(timedelta(hours=9))


def _default_service():
    from interactive.actions import calendar_add
    return calendar_add._build_service()


def _calendar_id():
    from interactive.actions import calendar_add
    return calendar_add.CALENDAR_ID


def run(now_iso: str, service=None, notify=None, store=None, lookback_hours: int = 2) -> int:
    """到来した未配達リマインダーを鳴らす。鳴らした件数を返す。"""
    if service is None:
        service = _default_service()
    if notify is None:
        from shared import pushcut_client
        notify = pushcut_client.notify_reminder
    if store is None:
        from interactive import reminder_store as store

    now = datetime.fromisoformat(now_iso)
    time_min = (now - timedelta(hours=lookback_hours)).isoformat()
    time_max = (now + timedelta(seconds=60)).isoformat()  # 今の分の予定を取りこぼさない
    res = service.events().list(
        calendarId=_calendar_id(), timeMin=time_min, timeMax=time_max,
        singleEvents=True, orderBy="startTime",
    ).execute()

    fired = 0
    for e in res.get("items", []):
        summary = e.get("summary", "")
        if not summary.startswith(_MARK):
            continue
        eid = e.get("id", "")
        if not eid or store.is_delivered(eid):
            continue
        text = summary[len(_MARK):].strip()
        if notify(text, eid):
            store.mark_delivered(eid, now_iso=now_iso)
            fired += 1
    return fired


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    now = datetime.now(_JST).replace(microsecond=0).isoformat()
    count = run(now)
    print(f"[reminder_watch] {now} fired={count}")
