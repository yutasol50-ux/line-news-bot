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
