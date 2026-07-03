import json
import hermes_tools.calendar_tool as ct


def test_calendar_add_ok(monkeypatch):
    monkeypatch.setattr(ct, "_run",
                        lambda cmd, payload: {"ok": True, "link": "https://cal/x"})
    out = json.loads(ct.calendar_add("歯医者", "2026-07-04T15:00:00+09:00"))
    assert out["ok"] is True and out["link"] == "https://cal/x"


def test_calendar_read_ok(monkeypatch):
    monkeypatch.setattr(ct, "_run",
                        lambda cmd, payload: {"ok": True, "block": "・7/4 歯医者"})
    out = json.loads(ct.calendar_read())
    assert "歯医者" in out["block"]
