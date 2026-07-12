"""/reminder/done と /reminder/snooze(Pushcutボタン用・トークン認証)のテスト。"""
import interactive.server as server


def _client():
    server.app.config["TESTING"] = True
    return server.app.test_client()


def _auth(monkeypatch):
    monkeypatch.setenv("REMINDER_TOKEN", "sek")
    return {"X-Reminder-Token": "sek"}


def test_done_deletes_active_event(monkeypatch):
    hdr = _auth(monkeypatch)
    deleted, cleared = [], []
    monkeypatch.setattr(server.reminder_store, "get_active", lambda: "ev1")
    monkeypatch.setattr(server.reminder_store, "clear", lambda e: cleared.append(e))
    monkeypatch.setattr(server.calendar_add, "delete_event", lambda e: deleted.append(e))
    r = _client().post("/reminder/done", headers=hdr)
    assert r.status_code == 200 and r.get_json()["status"] == "done"
    assert deleted == ["ev1"] and cleared == ["ev1"]


def test_snooze_reschedules_and_clears(monkeypatch):
    hdr = _auth(monkeypatch)
    moved, cleared = [], []
    monkeypatch.setattr(server.reminder_store, "get_active", lambda: "ev1")
    monkeypatch.setattr(server.reminder_store, "clear", lambda e: cleared.append(e))
    monkeypatch.setattr(server.calendar_add, "reschedule",
                        lambda e, start: moved.append((e, start)))
    r = _client().post("/reminder/snooze?minutes=10", headers=hdr)
    assert r.status_code == 200 and r.get_json()["status"] == "snoozed"
    assert moved and moved[0][0] == "ev1"       # ev1 を移動
    assert cleared == ["ev1"]                    # 既配達を外して再発火可能に


def test_explicit_event_id_overrides_active(monkeypatch):
    hdr = _auth(monkeypatch)
    deleted = []
    monkeypatch.setattr(server.reminder_store, "get_active", lambda: "active-ev")
    monkeypatch.setattr(server.reminder_store, "clear", lambda e: None)
    monkeypatch.setattr(server.calendar_add, "delete_event", lambda e: deleted.append(e))
    r = _client().post("/reminder/done?event_id=chosen", headers=hdr)
    assert r.status_code == 200
    assert deleted == ["chosen"]


def test_bad_token_401(monkeypatch):
    _auth(monkeypatch)
    r = _client().post("/reminder/done", headers={"X-Reminder-Token": "wrong"})
    assert r.status_code == 401


def test_no_active_returns_gone(monkeypatch):
    hdr = _auth(monkeypatch)
    monkeypatch.setattr(server.reminder_store, "get_active", lambda: None)
    r = _client().post("/reminder/done", headers=hdr)
    assert r.status_code == 200 and r.get_json()["status"] == "gone"
