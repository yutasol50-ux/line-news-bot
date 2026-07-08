# tests/test_approval_postback.py
import importlib
from unittest.mock import patch


def _server(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE", str(tmp_path / "p.json"))
    from interactive import server, approval_store
    importlib.reload(approval_store)
    importlib.reload(server)
    return server, approval_store


PROMPT = "Do you want to proceed?\n❯ 1. Yes\n  2. no\n  3. No (esc)\n"


def test_owner_tap_injects_when_still_pending(tmp_path, monkeypatch):
    server, store = _server(tmp_path, monkeypatch)
    store.register("%3", "~/x", "Q?", [{"key": "1", "label": "Yes"}],
                   now_iso="t", token="tok")
    with patch("interactive.server.line_client.LINE_USER_ID", "OWNER"), \
         patch("interactive.server.tmux_inject.capture", return_value=PROMPT), \
         patch("interactive.server.tmux_inject.send_key", return_value=True) as send, \
         patch("interactive.server.line_client.push", return_value=True):
        server.handle_postback("approve:tok:1", "OWNER")
    send.assert_called_once_with("%3", "1")
    assert store.get("tok") is None  # resolved


def test_non_owner_ignored(tmp_path, monkeypatch):
    server, store = _server(tmp_path, monkeypatch)
    store.register("%3", "~/x", "Q?", [], now_iso="t", token="tok")
    with patch("interactive.server.line_client.LINE_USER_ID", "OWNER"), \
         patch("interactive.server.tmux_inject.send_key") as send:
        server.handle_postback("approve:tok:1", "SOMEONE_ELSE")
    assert not send.called
    assert store.get("tok") is not None  # 手つかず


def test_not_pending_does_not_inject(tmp_path, monkeypatch):
    server, store = _server(tmp_path, monkeypatch)
    store.register("%3", "~/x", "Q?", [], now_iso="t", token="tok")
    with patch("interactive.server.line_client.LINE_USER_ID", "OWNER"), \
         patch("interactive.server.tmux_inject.capture", return_value="idle\n❯\n"), \
         patch("interactive.server.tmux_inject.send_key") as send, \
         patch("interactive.server.line_client.push", return_value=True):
        server.handle_postback("approve:tok:1", "OWNER")
    assert not send.called
    assert store.get("tok") is None  # resolve はする(空振り確定)
