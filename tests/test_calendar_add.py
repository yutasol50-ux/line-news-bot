from unittest.mock import patch, MagicMock
from interactive.actions import calendar_add


def test_timed_event_inserted():
    inserted = {}
    fake_events = MagicMock()

    def fake_insert(calendarId=None, body=None):
        inserted["calendarId"] = calendarId
        inserted["body"] = body
        ex = MagicMock()
        ex.execute.return_value = {"htmlLink": "https://cal/x"}
        return ex

    fake_events.insert.side_effect = fake_insert
    fake_service = MagicMock()
    fake_service.events.return_value = fake_events
    with patch("interactive.actions.calendar_add._build_service", return_value=fake_service):
        link = calendar_add.add("歯医者", "2026-06-29T14:00:00+09:00",
                                 "2026-06-29T15:00:00+09:00", all_day=False)
    assert link == "https://cal/x"
    assert inserted["body"]["summary"] == "歯医者"
    assert inserted["body"]["start"]["dateTime"] == "2026-06-29T14:00:00+09:00"


def test_reminder_has_no_native_popup():
    """A案: 標準通知はOFF(Pushcutが鳴らす)。⏰マークと正確な開始時刻は持つ。"""
    inserted = {}
    fake_events = MagicMock()

    def fake_insert(calendarId=None, body=None):
        inserted["body"] = body
        ex = MagicMock()
        ex.execute.return_value = {"htmlLink": "https://cal/r"}
        return ex

    fake_events.insert.side_effect = fake_insert
    fake_service = MagicMock()
    fake_service.events.return_value = fake_events
    with patch("interactive.actions.calendar_add._build_service", return_value=fake_service):
        link = calendar_add.add_reminder("洗濯物を回す", "2026-07-12T05:30:00+09:00")
    assert link == "https://cal/r"
    body = inserted["body"]
    assert body["start"]["dateTime"] == "2026-07-12T05:30:00+09:00"
    assert body["summary"] == "⏰洗濯物を回す"
    # 二重通知を避けるため popup は付けない(overrides空)
    assert body["reminders"]["useDefault"] is False
    assert body["reminders"]["overrides"] == []


def test_delete_event_calls_api():
    fake_events = MagicMock()
    ex = MagicMock(); ex.execute.return_value = {}
    fake_events.delete.return_value = ex
    fake_service = MagicMock(); fake_service.events.return_value = fake_events
    with patch("interactive.actions.calendar_add._build_service", return_value=fake_service):
        calendar_add.delete_event("ev1")
    assert fake_events.delete.call_args.kwargs["eventId"] == "ev1"


def test_reschedule_patches_start_and_end():
    fake_events = MagicMock()
    ex = MagicMock(); ex.execute.return_value = {}
    fake_events.patch.return_value = ex
    fake_service = MagicMock(); fake_service.events.return_value = fake_events
    with patch("interactive.actions.calendar_add._build_service", return_value=fake_service):
        calendar_add.reschedule("ev1", "2026-07-12T05:40:00+09:00")
    body = fake_events.patch.call_args.kwargs["body"]
    assert body["start"]["dateTime"] == "2026-07-12T05:40:00+09:00"
    assert body["end"]["dateTime"] == "2026-07-12T05:45:00+09:00"  # +5分


def test_all_day_event_uses_date():
    fake_events = MagicMock()
    ex = MagicMock()
    ex.execute.return_value = {"htmlLink": "https://cal/y"}
    fake_events.insert.return_value = ex
    fake_service = MagicMock()
    fake_service.events.return_value = fake_events
    with patch("interactive.actions.calendar_add._build_service", return_value=fake_service):
        calendar_add.add("健康診断", "2026-07-01T00:00:00+09:00", None, all_day=True)
    body = fake_events.insert.call_args.kwargs["body"]
    assert body["start"]["date"] == "2026-07-01"
    assert "dateTime" not in body["start"]
