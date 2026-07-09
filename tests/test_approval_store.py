import importlib
from interactive import approval_store as store


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE", str(tmp_path / "p.json"))
    importlib.reload(store)
    return store


def test_register_then_get(tmp_path, monkeypatch):
    s = _fresh(tmp_path, monkeypatch)
    s.register("%3", "~/x", "Q?", [{"key": "1", "label": "Yes"}],
               now_iso="2026-07-08T12:00:00+09:00", token="tok1")
    e = s.get("tok1")
    assert e["pane"] == "%3"
    assert e["choices"][0]["key"] == "1"
    assert e["state"] == "pending"


def test_get_missing_returns_none(tmp_path, monkeypatch):
    s = _fresh(tmp_path, monkeypatch)
    assert s.get("nope") is None


def test_resolve_marks_done(tmp_path, monkeypatch):
    s = _fresh(tmp_path, monkeypatch)
    s.register("%3", "~/x", "Q?", [], now_iso="t", token="tok1")
    s.resolve("tok1")
    assert s.get("tok1") is None  # pending でなくなる


def test_pending_panes(tmp_path, monkeypatch):
    s = _fresh(tmp_path, monkeypatch)
    s.register("%1", "~/a", "Q", [], now_iso="t", token="t1")
    s.register("%2", "~/b", "Q", [], now_iso="t", token="t2")
    s.resolve("t1")
    assert s.pending_panes() == ["%2"]


def test_pending_entries_returns_full_entries(tmp_path, monkeypatch):
    s = _fresh(tmp_path, monkeypatch)
    s.register("%1", "~/a", "Qa", [{"key": "1", "label": "Yes"}],
               now_iso="t1", token="t1")
    s.register("%2", "~/b", "Qb", [], now_iso="t2", token="t2")
    s.resolve("t1")
    entries = s.pending_entries()
    assert [e["token"] for e in entries] == ["t2"]
    assert entries[0]["question"] == "Qb"
    assert entries[0]["pane"] == "%2"
