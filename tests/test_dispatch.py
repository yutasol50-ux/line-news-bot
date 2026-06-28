from interactive import dispatch

NOW = "2026-06-28T22:00:00+09:00"


def test_dispatch_calendar(monkeypatch):
    monkeypatch.setattr(dispatch.intent, "parse_intent", lambda t, n: {
        "action": "add_calendar_event",
        "params": {"title": "歯医者", "start": "2026-06-29T14:00:00+09:00",
                   "end": None, "all_day": False}, "message": ""})
    monkeypatch.setattr(dispatch.calendar_add, "add", lambda **k: "https://cal/x")
    msg = dispatch.handle("明日14時歯医者", NOW)
    assert "歯医者" in msg and "登録" in msg


def test_dispatch_memo(monkeypatch):
    monkeypatch.setattr(dispatch.intent, "parse_intent", lambda t, n: {
        "action": "add_memo", "params": {"content": "牛乳", "tags": []}, "message": ""})
    monkeypatch.setattr(dispatch.notion_memo, "add", lambda **k: "https://notion/x")
    msg = dispatch.handle("牛乳メモ", NOW)
    assert "メモ" in msg


def test_dispatch_failure_is_honest(monkeypatch):
    monkeypatch.setattr(dispatch.intent, "parse_intent", lambda t, n: {
        "action": "add_memo", "params": {"content": "x", "tags": []}, "message": ""})

    def boom(**k):
        raise RuntimeError("api down")

    monkeypatch.setattr(dispatch.notion_memo, "add", boom)
    msg = dispatch.handle("メモして", NOW)
    assert "失敗" in msg
