# tests/test_pushcut_client.py
"""Pushcut 通知クライアント: 秘密キー越しに notification をトリガーする。"""
import importlib
from unittest.mock import patch, MagicMock


def _fresh(monkeypatch, secret="sek", name="承認待ち"):
    # secret=None は「未設定」を表すが、reload時の load_dotenv が .env の実キーで
    # 上書きしないよう、空文字を明示セットする(load_dotenvは既存キーを上書きしない)。
    monkeypatch.setenv("PUSHCUT_SECRET", "" if secret is None else secret)
    monkeypatch.setenv("PUSHCUT_NOTIFICATION", name)
    from shared import pushcut_client
    importlib.reload(pushcut_client)
    return pushcut_client


def test_notify_posts_to_secret_and_notification_url(monkeypatch):
    pc = _fresh(monkeypatch, secret="mysecret", name="承認待ち")
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        m = MagicMock(); m.status_code = 200; m.text = "ok"
        return m

    with patch("shared.pushcut_client.requests.post", side_effect=fake_post):
        ok = pc.notify(title="🔐 承認待ち", text="Do you want to proceed?")
    assert ok is True
    # URL は https://api.pushcut.io/<secret>/notifications/<name(URLエンコード)>
    assert captured["url"].startswith("https://api.pushcut.io/mysecret/notifications/")
    assert "%E6%89%BF%E8%AA%8D%E5%BE%85%E3%81%A1" in captured["url"]  # 承認待ち のURLエンコード
    assert captured["json"]["title"] == "🔐 承認待ち"
    assert captured["json"]["text"] == "Do you want to proceed?"


def test_notify_noop_when_secret_missing(monkeypatch):
    pc = _fresh(monkeypatch, secret=None)
    with patch("shared.pushcut_client.requests.post") as post:
        ok = pc.notify(title="x", text="y")
    assert ok is False
    assert not post.called  # 未設定なら何もしない(グレースフル)


def test_notify_false_on_error_status(monkeypatch):
    pc = _fresh(monkeypatch, secret="s")
    m = MagicMock(); m.status_code = 500; m.text = "boom"
    with patch("shared.pushcut_client.requests.post", return_value=m):
        ok = pc.notify(title="x", text="y")
    assert ok is False


def test_notify_false_on_exception(monkeypatch):
    pc = _fresh(monkeypatch, secret="s")
    with patch("shared.pushcut_client.requests.post", side_effect=RuntimeError("net")):
        ok = pc.notify(title="x", text="y")
    assert ok is False
