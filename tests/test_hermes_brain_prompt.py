"""hermes_brain.ask() が web発火を促すシステムプロンプトを必ず送ることを検証。"""
import interactive.hermes_brain as hb


class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


def test_ask_sends_system_prompt_with_web_rule(monkeypatch):
    captured = {}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return _FakeResp()

    monkeypatch.setattr(hb.requests, "post", _fake_post)
    out = hb.ask("東京の天気を調べて")

    assert out == "ok"
    msgs = captured["payload"]["messages"]
    # 先頭がsystem、次がuser
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"
    # webツールで裏を取る鉄則が入っている
    assert "web" in msgs[0]["content"]
    assert "捏造" in msgs[0]["content"]
    # ユーザー本文は保持される
    assert "東京の天気を調べて" in msgs[-1]["content"]
