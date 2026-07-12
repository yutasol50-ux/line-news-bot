from interactive.actions import cli


def test_calendar_add_dispatch(monkeypatch):
    monkeypatch.setattr(cli, "_calendar_add",
                        lambda **k: "https://cal/x")
    out = cli.main(["cli", "calendar_add",
                    '{"title":"歯医者","start":"2026-07-04T15:00:00+09:00"}'])
    assert out["ok"] is True
    assert out["link"] == "https://cal/x"


def test_reminder_add_dispatch(monkeypatch):
    monkeypatch.setattr(cli, "_reminder_add", lambda **k: "https://cal/r")
    out = cli.main(["cli", "reminder_add",
                    '{"text":"洗濯物を回す","at":"2026-07-12T05:30:00+09:00"}'])
    assert out["ok"] is True
    assert out["link"] == "https://cal/r"


def test_memo_add_dispatch(monkeypatch):
    monkeypatch.setattr(cli, "_memo_add", lambda **k: "https://notion/x")
    out = cli.main(["cli", "memo_add", '{"content":"牛乳を買う"}'])
    assert out["ok"] is True
    assert out["url"] == "https://notion/x"


def test_calendar_read_dispatch(monkeypatch):
    monkeypatch.setattr(cli, "_calendar_read", lambda: "・7/4 歯医者 15:00")
    out = cli.main(["cli", "calendar_read"])
    assert out["ok"] is True
    assert "歯医者" in out["block"]


def test_unknown_command():
    out = cli.main(["cli", "nope"])
    assert out["ok"] is False
    assert "unknown" in out["error"]
