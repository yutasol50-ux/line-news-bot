"""vision.read(画像/PDFをHaikuでテキスト化)のテスト。API本体はモックする。"""
import base64
import interactive.vision as vision


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _patch_post(monkeypatch, capture):
    def _post(url, headers=None, json=None, timeout=None):
        capture["url"] = url
        capture["headers"] = headers
        capture["json"] = json
        return _Resp({"content": [{"type": "text", "text": "領収書 3200円 5/1"}]})
    monkeypatch.setattr(vision.requests, "post", _post)


def test_read_image_sends_image_block_and_returns_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cap = {}
    _patch_post(monkeypatch, cap)
    out = vision.read(b"\xff\xd8rawjpeg", "image/jpeg")

    assert out == "領収書 3200円 5/1"
    assert cap["json"]["model"] == "claude-haiku-4-5"
    blocks = cap["json"]["messages"][0]["content"]
    kinds = [b["type"] for b in blocks]
    assert "image" in kinds                    # 画像ブロックが入る
    img = next(b for b in blocks if b["type"] == "image")
    assert img["source"]["type"] == "base64"
    assert img["source"]["media_type"].startswith("image/")
    # dataは正しくbase64（デコードできる）
    base64.b64decode(img["source"]["data"])


def test_read_pdf_sends_document_block(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cap = {}
    _patch_post(monkeypatch, cap)
    out = vision.read(b"%PDF-1.4 fake", "application/pdf")

    assert out == "領収書 3200円 5/1"
    blocks = cap["json"]["messages"][0]["content"]
    doc = next(b for b in blocks if b["type"] == "document")
    assert doc["source"]["media_type"] == "application/pdf"


def test_read_unsupported_media_type_returns_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # postが呼ばれたら失敗させる（呼ばれないことの確認）
    monkeypatch.setattr(vision.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("呼ぶな")))
    assert vision.read(b"data", "application/vnd.ms-excel") == ""


def test_read_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert vision.read(b"data", "image/jpeg") == ""


def test_read_api_error_returns_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(vision.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert vision.read(b"data", "image/jpeg") == ""
