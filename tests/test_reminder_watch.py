import importlib
from unittest.mock import MagicMock


def _reload_store(tmp_path, monkeypatch):
    monkeypatch.setenv("REMINDER_STORE", str(tmp_path / "state.json"))
    import interactive.reminder_store as rs
    importlib.reload(rs)
    return rs


def _fake_service(items):
    ex = MagicMock()
    ex.execute.return_value = {"items": items}
    events = MagicMock()
    events.list.return_value = ex
    svc = MagicMock()
    svc.events.return_value = events
    return svc


NOW = "2026-07-12T05:30:00+09:00"


def test_due_reminder_notifies_and_marks(tmp_path, monkeypatch):
    rs = _reload_store(tmp_path, monkeypatch)
    import interactive.reminder_watch as rw
    importlib.reload(rw)
    svc = _fake_service([
        {"id": "ev1", "summary": "⏰洗濯物を回す",
         "start": {"dateTime": "2026-07-12T05:30:00+09:00"}},
    ])
    sent = []
    n = rw.run(now_iso=NOW, service=svc, notify=lambda t, e=None: sent.append(t) or True, store=rs)
    assert n == 1
    assert sent == ["洗濯物を回す"]           # ⏰プレフィクスを剥がした本文
    assert rs.is_delivered("ev1") is True
    assert rs.get_active() == "ev1"


def test_already_delivered_not_renotified(tmp_path, monkeypatch):
    rs = _reload_store(tmp_path, monkeypatch)
    import interactive.reminder_watch as rw
    importlib.reload(rw)
    rs.mark_delivered("ev1", now_iso=NOW)
    svc = _fake_service([
        {"id": "ev1", "summary": "⏰洗濯物を回す",
         "start": {"dateTime": "2026-07-12T05:30:00+09:00"}},
    ])
    sent = []
    n = rw.run(now_iso=NOW, service=svc, notify=lambda t, e=None: sent.append(t) or True, store=rs)
    assert n == 0
    assert sent == []


def test_non_reminder_event_ignored(tmp_path, monkeypatch):
    rs = _reload_store(tmp_path, monkeypatch)
    import interactive.reminder_watch as rw
    importlib.reload(rw)
    svc = _fake_service([
        {"id": "appt", "summary": "歯医者",
         "start": {"dateTime": "2026-07-12T05:30:00+09:00"}},
    ])
    sent = []
    n = rw.run(now_iso=NOW, service=svc, notify=lambda t, e=None: sent.append(t) or True, store=rs)
    assert n == 0
    assert rs.is_delivered("appt") is False
