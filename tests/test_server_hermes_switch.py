import interactive.server as server


def test_process_uses_hermes_when_on(monkeypatch):
    monkeypatch.setenv("HERMES_BRAIN", "on")
    sent = {}
    monkeypatch.setattr(server, "hermes_brain",
                        type("M", (), {"ask": staticmethod(lambda t, sid="line-owner": f"H:{t}")}))
    monkeypatch.setattr(server.line_client, "reply", lambda rt, msg: sent.setdefault("msg", msg))
    server._process("やあ", "RT", "2026-07-03T10:00:00+09:00")
    assert sent["msg"] == "H:やあ"


def test_process_uses_gemini_when_off(monkeypatch):
    monkeypatch.setenv("HERMES_BRAIN", "off")
    sent = {}
    monkeypatch.setattr(server.dispatch, "handle", lambda t, n: f"G:{t}")
    monkeypatch.setattr(server.line_client, "reply", lambda rt, msg: sent.setdefault("msg", msg))
    server._process("やあ", "RT", "2026-07-03T10:00:00+09:00")
    assert sent["msg"] == "G:やあ"
