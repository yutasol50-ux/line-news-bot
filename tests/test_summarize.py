"""summarize: Haikuで本物の3点要約。失敗時は先頭刈りへフォールバック(絶対に例外を出さない)。"""
from interactive import summarize as sm


def test_summarize_uses_haiku_output(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"content": [{"type": "text", "text": "・要点1\n・要点2\n・要点3"}]}

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["key"] = headers.get("x-api-key")
        captured["model"] = json.get("model")
        return _Resp()

    monkeypatch.setattr(sm.requests, "post", _fake_post)

    out = sm.summarize("とても長いレポート本文" * 100)

    assert out == "・要点1\n・要点2\n・要点3"
    assert captured["key"] == "test-key"
    assert "haiku" in captured["model"]


def test_summarize_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _boom(*a, **k):  # キー無しでAPIを叩いてはいけない
        raise AssertionError("キー無しでAPIを叩いてはいけない")

    monkeypatch.setattr(sm.requests, "post", _boom)

    out = sm.summarize("本文" * 500, max_chars=50)

    assert out.startswith("本文")
    assert len(out) <= 60  # 先頭刈り(+ " …")


def test_summarize_falls_back_on_api_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(sm.requests, "post", _boom)

    out = sm.summarize("あいうえお" * 200, max_chars=30)

    assert out.startswith("あいうえお")  # フォールバックで中身は保たれる
