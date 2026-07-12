import json
from pathlib import Path
import importlib


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("REMINDER_STORE", str(tmp_path / "state.json"))
    import interactive.reminder_store as rs
    importlib.reload(rs)
    return rs


def test_mark_delivered_sets_active_and_flag(tmp_path, monkeypatch):
    rs = _store(tmp_path, monkeypatch)
    assert rs.is_delivered("ev1") is False
    rs.mark_delivered("ev1", now_iso="2026-07-12T05:30:00+09:00")
    assert rs.is_delivered("ev1") is True
    assert rs.get_active() == "ev1"


def test_active_is_latest_delivered(tmp_path, monkeypatch):
    rs = _store(tmp_path, monkeypatch)
    rs.mark_delivered("ev1", now_iso="2026-07-12T05:30:00+09:00")
    rs.mark_delivered("ev2", now_iso="2026-07-12T06:00:00+09:00")
    assert rs.get_active() == "ev2"


def test_clear_removes_flag_and_active(tmp_path, monkeypatch):
    rs = _store(tmp_path, monkeypatch)
    rs.mark_delivered("ev1", now_iso="2026-07-12T05:30:00+09:00")
    rs.clear("ev1")
    assert rs.is_delivered("ev1") is False
    assert rs.get_active() is None


def test_clear_other_keeps_active(tmp_path, monkeypatch):
    rs = _store(tmp_path, monkeypatch)
    rs.mark_delivered("ev1", now_iso="2026-07-12T05:30:00+09:00")
    rs.mark_delivered("ev2", now_iso="2026-07-12T06:00:00+09:00")
    rs.clear("ev1")
    assert rs.get_active() == "ev2"
    assert rs.is_delivered("ev2") is True


def test_persists_to_disk(tmp_path, monkeypatch):
    rs = _store(tmp_path, monkeypatch)
    rs.mark_delivered("ev1", now_iso="2026-07-12T05:30:00+09:00")
    data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "ev1" in data["delivered"]
    assert data["active"] == "ev1"
