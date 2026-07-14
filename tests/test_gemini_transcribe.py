import requests
import interactive.gemini_transcribe as gt


class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status; self._p = payload or {}; self.headers = headers or {}
    def json(self): return self._p
    @property
    def text(self): return str(self._p)
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(self.status_code)


def test_transcribe_retries_then_succeeds(monkeypatch, tmp_path):
    f = tmp_path / "a.m4a"; f.write_bytes(b"x" * 10)  # 小さい=inline
    calls = {"n": 0}
    def fake_post(url, **kw):
        if "generateContent" in url:
            calls["n"] += 1
            if calls["n"] == 1:
                return _Resp(503)
            return _Resp(200, {"candidates":[{"content":{"parts":[{"text":"こんにちは"}]}}]})
        return _Resp(200, {})
    text = gt.transcribe(str(f), post=fake_post, sleep=lambda s: None)
    assert text == "こんにちは"
    assert calls["n"] == 2  # 1回503→リトライで成功


def test_transcribe_connection_error_does_not_leak_api_key(monkeypatch, tmp_path):
    """DNS/timeout/refused等の接続エラーはURL(?key=...)ごと例外文字列に載る。
    voice_intake.process の `except ... print(...)` からjournalctlに漏れないよう、
    URL/キーを含まない安全なRuntimeErrorへ包み直す(Finding 1)。"""
    monkeypatch.setenv("GEMINI_API_KEY", "SECRET")
    f = tmp_path / "a.m4a"; f.write_bytes(b"x" * 10)

    def fake_post(url, **kw):
        # requestsの実際の挙動を模す: 接続エラーメッセージにURL全体が含まれる。
        raise requests.exceptions.ConnectionError(
            f"Connection refused for url: {url}"
        )

    import pytest
    with pytest.raises(RuntimeError) as exc:
        gt.transcribe(str(f), post=fake_post, sleep=lambda s: None)
    msg = str(exc.value)
    assert "SECRET" not in msg
    assert "key=" not in msg


def test_transcribe_retries_after_connection_error_then_succeeds(monkeypatch, tmp_path):
    """接続エラーは即失敗ではなく、既存の指数バックオフでリトライされる(一過性の想定)。"""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    f = tmp_path / "a.m4a"; f.write_bytes(b"x" * 10)
    calls = {"n": 0}
    sleeps = []

    def fake_post(url, **kw):
        if "generateContent" in url:
            calls["n"] += 1
            if calls["n"] == 1:
                raise requests.exceptions.ConnectionError(f"boom {url}")
            return _Resp(200, {"candidates": [{"content": {"parts": [{"text": "こんにちは"}]}}]})
        return _Resp(200, {})

    text = gt.transcribe(str(f), post=fake_post, sleep=sleeps.append)
    assert text == "こんにちは"
    assert calls["n"] == 2  # 1回目は接続エラー→リトライで成功
    assert len(sleeps) == 1


def test_transcribe_missing_api_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    f = tmp_path / "a.m4a"; f.write_bytes(b"x" * 10)
    import pytest
    with pytest.raises(RuntimeError):
        gt.transcribe(str(f), post=lambda *a, **k: _Resp(200), sleep=lambda s: None)


def test_transcribe_falls_back_to_flash_lite(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    f = tmp_path / "a.m4a"; f.write_bytes(b"x" * 10)
    seen_models = []
    def fake_post(url, **kw):
        if "generateContent" in url:
            model = url.split("/models/")[1].split(":")[0]
            seen_models.append(model)
            if model == "gemini-2.5-flash":
                return _Resp(503)
            return _Resp(200, {"candidates": [{"content": {"parts": [{"text": "フォールバック成功"}]}}]})
        return _Resp(200, {})
    sleeps = []
    text = gt.transcribe(str(f), post=fake_post, sleep=sleeps.append)
    assert text == "フォールバック成功"
    assert seen_models.count("gemini-2.5-flash") == 5  # 5回リトライして諦める
    assert "gemini-2.5-flash-lite" in seen_models
    assert len(sleeps) == 5  # flashの各リトライ前にsleep


def test_transcribe_gives_up_after_both_models_fail(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    f = tmp_path / "a.m4a"; f.write_bytes(b"x" * 10)
    def fake_post(url, **kw):
        if "generateContent" in url:
            return _Resp(503)
        return _Resp(200, {})
    import pytest
    with pytest.raises(RuntimeError):
        gt.transcribe(str(f), post=fake_post, sleep=lambda s: None)


def test_transcribe_uses_file_api_for_large_files(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    f = tmp_path / "big.m4a"; f.write_bytes(b"x" * (8 * 1024 * 1024))  # >7MB
    calls = {"upload_start": 0, "upload_bytes": 0, "generate": 0}
    def fake_post(url, **kw):
        if "upload/v1beta/files" in url:
            calls["upload_start"] += 1
            return _Resp(200, headers={"X-Goog-Upload-URL": "https://upload.example/abc"})
        if url == "https://upload.example/abc":
            calls["upload_bytes"] += 1
            return _Resp(200, {"file": {"name": "files/abc", "uri": "https://files/abc", "state": "ACTIVE"}})
        if "generateContent" in url:
            calls["generate"] += 1
            return _Resp(200, {"candidates": [{"content": {"parts": [{"text": "大きいファイルの文字起こし"}]}}]})
        raise AssertionError(f"unexpected url {url}")
    text = gt.transcribe(str(f), post=fake_post, sleep=lambda s: None)
    assert text == "大きいファイルの文字起こし"
    assert calls["upload_start"] == 1
    assert calls["upload_bytes"] == 1
    assert calls["generate"] == 1


class _Resp403:
    """resp.url に ?key=SECRET を含む本物のrequestsレスポンスを模す。
    raise_for_status() を呼べば requests.exceptions.HTTPError が
    そのURL(=APIキー)ごとメッセージに乗ることを示すための罠として持たせておき、
    実装が raise_for_status() を呼んでいない(=罠を踏んでいない)ことを検証する。"""
    def __init__(self, url, status=403):
        self.status_code = status
        self.url = url
        self.headers = {}
        self.text = "Forbidden"

    def raise_for_status(self):
        import requests as _r
        raise _r.exceptions.HTTPError(
            f"{self.status_code} Client Error: Forbidden for url: {self.url}"
        )

    def json(self):
        return {}


def test_upload_start_403_does_not_leak_api_key(monkeypatch, tmp_path):
    """File API アップロード開始(start)が403を返しても、
    resp.url(?key=SECRETKEY)がエラーメッセージに漏れない(raise_for_status()を使わない)。"""
    monkeypatch.setenv("GEMINI_API_KEY", "SECRETKEY")
    f = tmp_path / "big.m4a"; f.write_bytes(b"x" * (8 * 1024 * 1024))  # >7MB => File API経由

    def fake_post(url, **kw):
        if "upload/v1beta/files" in url:
            return _Resp403(url)
        raise AssertionError(f"generateContentまで到達すべきでない: {url}")

    import pytest
    with pytest.raises(RuntimeError) as exc:
        gt.transcribe(str(f), post=fake_post, get=lambda *a, **k: _Resp(200), sleep=lambda s: None)
    msg = str(exc.value)
    assert "SECRETKEY" not in msg
    assert "key=" not in msg


def test_upload_send_403_does_not_leak_api_key(monkeypatch, tmp_path):
    """resumableアップロード本体の送信(up)が403でも同様にキーが漏れない。"""
    monkeypatch.setenv("GEMINI_API_KEY", "SECRETKEY")
    f = tmp_path / "big.m4a"; f.write_bytes(b"x" * (8 * 1024 * 1024))

    def fake_post(url, **kw):
        if "upload/v1beta/files" in url:
            return _Resp(200, headers={"X-Goog-Upload-URL": "https://upload.example/abc?key=SECRETKEY"})
        if url.startswith("https://upload.example/abc"):
            return _Resp403(url)
        raise AssertionError(f"generateContentまで到達すべきでない: {url}")

    import pytest
    with pytest.raises(RuntimeError) as exc:
        gt.transcribe(str(f), post=fake_post, get=lambda *a, **k: _Resp(200), sleep=lambda s: None)
    msg = str(exc.value)
    assert "SECRETKEY" not in msg
    assert "key=" not in msg


def test_upload_file_directly_403_does_not_leak_key(monkeypatch, tmp_path):
    """_upload_file を直接叩いても(File API path強制ではなく)、start/up双方の403でキーが漏れない。"""
    monkeypatch.setenv("GEMINI_API_KEY", "SECRETKEY")
    f = tmp_path / "any.m4a"; f.write_bytes(b"x" * 10)

    def fake_post(url, **kw):
        return _Resp403(url)

    import pytest
    with pytest.raises(RuntimeError) as exc:
        gt._upload_file(str(f), "audio/mp4", post=fake_post, get=lambda *a, **k: _Resp(200))
    msg = str(exc.value)
    assert "SECRETKEY" not in msg
    assert "key=" not in msg


def test_upload_file_poll_403_does_not_leak_key(monkeypatch, tmp_path):
    """file-state のポーリング(get)が403でもキーが漏れない。"""
    monkeypatch.setenv("GEMINI_API_KEY", "SECRETKEY")
    f = tmp_path / "any.m4a"; f.write_bytes(b"x" * 10)

    def fake_post(url, **kw):
        if "upload/v1beta/files" in url:
            return _Resp(200, headers={"X-Goog-Upload-URL": "https://upload.example/abc"})
        return _Resp(200, {"file": {"name": "files/abc", "uri": "https://files/abc", "state": "PROCESSING"}})

    def fake_get(url, **kw):
        return _Resp403(url)

    import pytest
    with pytest.raises(RuntimeError) as exc:
        gt._upload_file(str(f), "audio/mp4", post=fake_post, get=fake_get, sleep=lambda s: None)
    msg = str(exc.value)
    assert "SECRETKEY" not in msg
    assert "key=" not in msg


def test_transcribe_long_concatenates_chunks(monkeypatch, tmp_path):
    f = tmp_path / "long.m4a"; f.write_bytes(b"x" * 10)
    def fake_split(path, chunk_sec, workdir):
        return [str(tmp_path / "chunk_000.m4a"), str(tmp_path / "chunk_001.m4a")]
    def fake_transcribe(path):
        return "前半" if path.endswith("000.m4a") else "後半"
    text = gt.transcribe_long(str(f), split=fake_split, transcribe=fake_transcribe)
    assert text == "前半\n後半"


def test_transcribe_long_single_chunk_calls_transcribe_directly(monkeypatch, tmp_path):
    f = tmp_path / "short.m4a"; f.write_bytes(b"x" * 10)
    def fake_split(path, chunk_sec, workdir):
        return [str(tmp_path / "chunk_000.m4a")]
    calls = {"direct": 0}
    def fake_transcribe(path):
        calls["direct"] += 1
        assert path == str(f)  # 分割結果が1個以下なら元ファイルを直接渡す
        return "そのまま"
    text = gt.transcribe_long(str(f), split=fake_split, transcribe=fake_transcribe)
    assert text == "そのまま"
    assert calls["direct"] == 1


def test_draft_note_splits_title_and_body(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    def fake_post(url, **kw):
        assert "generateContent" in url
        return _Resp(200, {"candidates": [{"content": {"parts": [
            {"text": "会議メモのタイトル\n\n## 要点\n- a\n- b\n\n本文..."}
        ]}}]})
    title, body = gt.draft_note("文字起こし全文", post=fake_post)
    assert title == "会議メモのタイトル"
    assert "## 要点" in body
    assert "本文..." in body


def test_draft_note_retries_on_503(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    calls = {"n": 0}
    def fake_post(url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(503)
        return _Resp(200, {"candidates": [{"content": {"parts": [{"text": "タイトル\n本文"}]}}]})
    title, body = gt.draft_note("文字起こし", post=fake_post, sleep=lambda s: None)
    assert title == "タイトル"
    assert body == "本文"
    assert calls["n"] == 2
