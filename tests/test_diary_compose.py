"""diary_compose: Haiku清書。失敗時は原文フォールバック(例外を出さない)。"""
from interactive import diary_compose as dc


class _Resp:
    def __init__(self, text): self._t = text
    def raise_for_status(self): pass
    def json(self): return {"content": [{"type": "text", "text": self._t}]}


def test_compose_parses_haiku_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    payload = '{"title":"職場の当務","tags":["疲れ","仕事"],"body":"今日は当務だった。"}'
    monkeypatch.setattr(dc.requests, "post", lambda *a, **k: _Resp(payload))
    out = dc.compose("・当務\n・つかれた", date="2026-07-07")
    assert out["title"] == "職場の当務"
    assert out["tags"] == ["疲れ", "仕事"]
    assert "当務" in out["body"]


def test_compose_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(dc.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("叩くな")))
    out = dc.compose("・箇条書きのまま", date="2026-07-07")
    assert out["title"] == "2026-07-07"
    assert out["tags"] == []
    assert out["body"] == "・箇条書きのまま"   # 原文は失わない


def test_compose_falls_back_on_bad_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(dc.requests, "post", lambda *a, **k: _Resp("これはJSONじゃない"))
    out = dc.compose("原文テキスト", date="2026-07-07")
    assert out["body"] == "原文テキスト"       # パース不能でも原文で保存
