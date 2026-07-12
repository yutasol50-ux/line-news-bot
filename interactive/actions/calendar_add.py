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


def delete_event(event_id: str) -> None:
    """予定を削除する(リマインダー完了=イベント削除)。"""
    service = _build_service()
    service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()


def reschedule(event_id: str, new_start_iso: str) -> None:
    """予定の開始/終了を動かす(スヌーズ=指定時刻へ移動、5分枠)。"""
    service = _build_service()
    start = datetime.fromisoformat(new_start_iso)
    end = (start + timedelta(minutes=5)).isoformat()
    body = {
        "start": {"dateTime": new_start_iso, "timeZone": "Asia/Tokyo"},
        "end": {"dateTime": end, "timeZone": "Asia/Tokyo"},
    }
    service.events().patch(calendarId=CALENDAR_ID, eventId=event_id, body=body).execute()


def add_reminder(text: str, at_iso: str) -> str:
    """リマインダー予定(⏰マーク付き)を台帳として作る。

    A案: カレンダー標準通知は付けない(overrides空)。通知は reminder_watch(cron)が
    Pushcutで鳴らす=完了/スヌーズのボタン付き。二重通知を避けるため popup は明示的にOFF。
    予定自体はスマホのカレンダーに見えるので「消えない台帳」の役割は保つ。
    """
    service = _build_service()
    start = datetime.fromisoformat(at_iso)
    end = (start + timedelta(minutes=5)).isoformat()
    body = {
        "summary": f"⏰{text}",
        "start": {"dateTime": at_iso, "timeZone": "Asia/Tokyo"},
        "end": {"dateTime": end, "timeZone": "Asia/Tokyo"},
        "reminders": {"useDefault": False, "overrides": []},  # 標準通知OFF(Pushcut一本)
    }
    created = service.events().insert(calendarId=CALENDAR_ID, body=body).execute()
    return created.get("htmlLink", "")
