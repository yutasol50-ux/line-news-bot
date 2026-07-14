from shared import telegram_client as tc


class _Resp:
    def __init__(self, status): self.status_code = status
    @property
    def text(self): return ""


def test_notify_sends_when_configured():
    calls = []
    def fake_post(url, **kw):
        calls.append((url, kw)); return _Resp(200)
    ok = tc.notify("やあ", token="123:ABC", chat_id="42", post=fake_post)
    assert ok is True
    url, kw = calls[0]
    assert "bot123:ABC/sendMessage" in url
    assert kw["data"]["chat_id"] == "42"
    assert kw["data"]["text"] == "やあ"


def test_notify_noop_when_unconfigured():
    calls = []
    ok = tc.notify("x", token="", chat_id="", post=lambda *a, **k: calls.append(1))
    assert ok is False
    assert calls == []


def test_notify_false_on_error_status():
    ok = tc.notify("x", token="t", chat_id="c", post=lambda *a, **k: _Resp(403))
    assert ok is False


def test_notify_swallows_exception():
    def boom(*a, **k): raise RuntimeError("net")
    ok = tc.notify("x", token="t", chat_id="c", post=boom)
    assert ok is False  # 例外でも落ちない
