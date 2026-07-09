# tests/test_bark_client.py
"""Bark 通知クライアント: 通知ごとにアイコン/サウンド/グループを変えられる。"""
import importlib
from unittest.mock import patch, MagicMock


def _fresh(monkeypatch, key="devkey"):
    monkeypatch.setenv("BARK_KEY", "" if key is None else key)
    from shared import bark_client
    importlib.reload(bark_client)
    return bark_client


def test_notify_posts_title_body_and_options(monkeypatch):
    bc = _fresh(monkeypatch, key="mykey")
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        m = MagicMock(); m.status_code = 200; m.text = '{"code":200}'
        return m

    with patch("shared.bark_client.requests.post", side_effect=fake_post):
        ok = bc.notify("承認待ち", "Do you want to proceed?",
                       icon="https://example.com/lock.png", group="approval", sound="bell")
    assert ok is True
    assert captured["url"] == "https://api.day.app/mykey"
    j = captured["json"]
    assert j["title"] == "承認待ち"
    assert j["body"] == "Do you want to proceed?"
    assert j["icon"] == "https://example.com/lock.png"
    assert j["group"] == "approval"
    assert j["sound"] == "bell"


def test_notify_omits_unset_options(monkeypatch):
    bc = _fresh(monkeypatch, key="k")
    captured = {}
    with patch("shared.bark_client.requests.post",
               side_effect=lambda url, json=None, timeout=None: captured.update(json=json)
               or MagicMock(status_code=200, text="ok")):
        bc.notify("t", "b")
    # icon/group/sound 未指定なら送らない(キー自体が無い)
    assert "icon" not in captured["json"]
    assert "group" not in captured["json"]
    assert "sound" not in captured["json"]


def test_notify_noop_when_key_missing(monkeypatch):
    bc = _fresh(monkeypatch, key=None)
    with patch("shared.bark_client.requests.post") as post:
        ok = bc.notify("t", "b")
    assert ok is False
    assert not post.called


def test_notify_false_on_error_status(monkeypatch):
    bc = _fresh(monkeypatch, key="k")
    m = MagicMock(); m.status_code = 500; m.text = "boom"
    with patch("shared.bark_client.requests.post", return_value=m):
        assert bc.notify("t", "b") is False


def test_notify_false_on_exception(monkeypatch):
    bc = _fresh(monkeypatch, key="k")
    with patch("shared.bark_client.requests.post", side_effect=RuntimeError("net")):
        assert bc.notify("t", "b") is False
