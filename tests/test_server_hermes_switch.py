import interactive.server as server


def test_process_uses_hermes_when_on(monkeypatch):
    monkeypatch.setenv("HERMES_BRAIN", "on")
    got = {}
    # HERMES_BRAIN=on では自己昇格ディスパッチャに委譲する。
    monkeypatch.setattr(server.research_async, "handle",
                        lambda text, rt, sid="line-owner": got.update(text=text, rt=rt, sid=sid))
    server._process("やあ", "RT", "2026-07-03T10:00:00+09:00")
    assert got == {"text": "やあ", "rt": "RT", "sid": "line-owner"}


def test_process_uses_gemini_when_off(monkeypatch):
    monkeypatch.setenv("HERMES_BRAIN", "off")
    sent = {}
    monkeypatch.setattr(server.dispatch, "handle", lambda t, n: f"G:{t}")
    monkeypatch.setattr(server.line_client, "reply", lambda rt, msg: sent.setdefault("msg", msg))
    server._process("やあ", "RT", "2026-07-03T10:00:00+09:00")
    assert sent["msg"] == "G:やあ"
