"""diary_classify: 返信の意図(affirm/reject/more/content)。API失敗はキーワードで凌ぐ。"""
from interactive import diary_classify as dcl


class _Resp:
    def __init__(self, label): self._l = label
    def raise_for_status(self): pass
    def json(self): return {"content": [{"type": "text", "text": self._l}]}


def test_haiku_label_is_used(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(dcl.requests, "post", lambda *a, **k: _Resp("affirm"))
    assert dcl.classify("うん、それでいいよ") == "affirm"


def test_keyword_fallback_affirm_on_api_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(dcl.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert dcl.classify("おけ") == "affirm"
    assert dcl.classify("終わり！") == "affirm"


def test_keyword_fallback_content_default(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(dcl.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    # 中身っぽい文はフォールバックでも content(取りこぼさない)
    assert dcl.classify("今日は駅で人身事故対応でバタバタした") == "content"
