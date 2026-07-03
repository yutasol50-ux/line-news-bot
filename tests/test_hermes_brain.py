import interactive.hermes_brain as hb


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_ask_returns_content(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _Resp({"choices": [{"message": {"content": "やあ、了解！"}}]})

    monkeypatch.setattr(hb.requests, "post", fake_post)
    out = hb.ask("こんにちは", "line-owner")
    assert out == "やあ、了解！"
    assert captured["headers"]["X-Hermes-Session-Id"] == "line-owner"
    assert captured["json"]["messages"][0]["content"] == "こんにちは"


def test_ask_on_error_returns_safe_message(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(hb.requests, "post", boom)
    out = hb.ask("こんにちは", "line-owner")
    assert "調子が悪い" in out
