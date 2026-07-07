"""LINE content API(メディア本体取得)のテスト。"""
import interactive.line_media as line_media


class _Resp:
    def __init__(self, content, ctype, status=200):
        self.content = content
        self.headers = {"Content-Type": ctype}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_content_hits_data_endpoint_with_auth(monkeypatch):
    seen = {}

    def _get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        return _Resp(b"\xff\xd8jpegbytes", "image/jpeg; charset=binary")

    monkeypatch.setattr(line_media.requests, "get", _get)
    data, ctype = line_media.fetch_content("MID123", token="TKN")

    assert data == b"\xff\xd8jpegbytes"
    assert ctype == "image/jpeg"                       # パラメータ除去・小文字化
    assert seen["url"] == "https://api-data.line.me/v2/bot/message/MID123/content"
    assert seen["headers"]["Authorization"] == "Bearer TKN"


def test_fetch_content_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(line_media.requests, "get",
                        lambda url, headers=None, timeout=None: _Resp(b"", "text/html", status=404))
    try:
        line_media.fetch_content("MID", token="TKN")
        assert False, "例外が出るべき"
    except Exception:
        pass
