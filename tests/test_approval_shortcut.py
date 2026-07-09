# tests/test_approval_shortcut.py
"""ショートカット用の窓口: GET /approval/pending と POST /approval/answer。"""
import importlib
from unittest.mock import patch


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_TOKEN", "sekret")
    monkeypatch.setenv("APPROVAL_STORE", str(tmp_path / "p.json"))
    from interactive import server
    importlib.reload(server)
    server.app.config["TESTING"] = True
    return server


PROMPT = "Do you want to proceed?\n❯ 1. Yes\n  3. No (esc)\n"


# --- GET /approval/pending ---

def test_pending_returns_current_when_registered(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    from interactive import approval_store
    approval_store.register(
        "%3", "~/x", "Do you want to proceed?",
        [{"key": "1", "label": "Yes"}, {"key": "3", "label": "No"}],
        now_iso="2026-07-09T10:00:00+09:00", token="tokA")
    r = server.app.test_client().get(
        "/approval/pending", headers={"X-Approval-Token": "sekret"})
    assert r.status_code == 200
    j = r.get_json()
    assert j["pending"] is True
    assert j["current"]["token"] == "tokA"
    assert j["current"]["question"] == "Do you want to proceed?"
    assert [c["key"] for c in j["current"]["choices"]] == ["1", "3"]


def test_pending_empty_when_none(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    r = server.app.test_client().get(
        "/approval/pending", headers={"X-Approval-Token": "sekret"})
    assert r.status_code == 200
    j = r.get_json()
    assert j["pending"] is False
    assert j["current"] is None


def test_pending_returns_latest_when_multiple(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    from interactive import approval_store
    approval_store.register("%1", "~/a", "old", [{"key": "1", "label": "Yes"}],
                            now_iso="2026-07-09T09:00:00+09:00", token="old")
    approval_store.register("%2", "~/b", "new", [{"key": "1", "label": "Yes"}],
                            now_iso="2026-07-09T10:00:00+09:00", token="new")
    r = server.app.test_client().get(
        "/approval/pending", headers={"X-Approval-Token": "sekret"})
    j = r.get_json()
    assert j["current"]["token"] == "new"  # created が新しい方
    assert j["count"] == 2


def test_pending_rejects_bad_token(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    r = server.app.test_client().get(
        "/approval/pending", headers={"X-Approval-Token": "wrong"})
    assert r.status_code == 401


# --- POST /approval/answer ---

def test_answer_injects_when_pending(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    from interactive import approval_store
    approval_store.register("%3", "~/x", "Do you want to proceed?",
                            [{"key": "1", "label": "Yes"}],
                            now_iso="t", token="tokB")
    with patch("interactive.server.tmux_inject.capture", return_value=PROMPT), \
         patch("interactive.server.tmux_inject.send_key", return_value=True) as send:
        r = server.app.test_client().post(
            "/approval/answer", json={"token": "tokB", "key": "1"},
            headers={"X-Approval-Token": "sekret"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "done"
    send.assert_called_once_with("%3", "1")
    assert approval_store.get("tokB") is None  # resolved


def test_answer_without_token_uses_latest_pending(tmp_path, monkeypatch):
    """token 省略時は「今出てる最新の承認」に答える(ショートカット簡易化)。"""
    server = _client(tmp_path, monkeypatch)
    from interactive import approval_store
    approval_store.register("%1", "~/a", "old", [{"key": "1", "label": "Yes"}],
                            now_iso="2026-07-09T09:00:00+09:00", token="old")
    approval_store.register("%9", "~/b", "new", [{"key": "1", "label": "Yes"}],
                            now_iso="2026-07-09T10:00:00+09:00", token="new")
    with patch("interactive.server.tmux_inject.capture", return_value=PROMPT), \
         patch("interactive.server.tmux_inject.send_key", return_value=True) as send:
        r = server.app.test_client().post(
            "/approval/answer", json={"key": "1"},  # token 無し
            headers={"X-Approval-Token": "sekret"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "done"
    send.assert_called_once_with("%9", "1")  # 最新(created新しい方)に注入
    assert approval_store.get("new") is None


def test_answer_without_token_gone_when_no_pending(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    r = server.app.test_client().post(
        "/approval/answer", json={"key": "1"},
        headers={"X-Approval-Token": "sekret"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "gone"


def test_answer_key_from_query_string(tmp_path, monkeypatch):
    """Pushcut等がBody無しでも使えるよう、keyをクエリ文字列でも受ける。"""
    server = _client(tmp_path, monkeypatch)
    from interactive import approval_store
    approval_store.register("%3", "~/x", "Q", [{"key": "1", "label": "Yes"}],
                            now_iso="t", token="tokQ")
    with patch("interactive.server.tmux_inject.capture", return_value=PROMPT), \
         patch("interactive.server.tmux_inject.send_key", return_value=True) as send:
        r = server.app.test_client().post(
            "/approval/answer?key=1",  # Body無し・クエリのみ
            headers={"X-Approval-Token": "sekret"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "done"
    send.assert_called_once_with("%3", "1")


def test_answer_gone_for_unknown_token(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    r = server.app.test_client().post(
        "/approval/answer", json={"token": "nope", "key": "1"},
        headers={"X-Approval-Token": "sekret"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "gone"


def test_answer_stale_when_not_prompt(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    from interactive import approval_store
    approval_store.register("%3", "~/x", "Q", [{"key": "1", "label": "Yes"}],
                            now_iso="t", token="tokC")
    with patch("interactive.server.tmux_inject.capture", return_value="idle\n❯\n"), \
         patch("interactive.server.tmux_inject.send_key") as send:
        r = server.app.test_client().post(
            "/approval/answer", json={"token": "tokC", "key": "1"},
            headers={"X-Approval-Token": "sekret"})
    assert r.get_json()["status"] == "stale"
    assert not send.called
    assert approval_store.get("tokC") is None  # resolve される(空振り確定)


def test_answer_missing_fields_400(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    r = server.app.test_client().post(
        "/approval/answer", json={"token": "x"},  # key 欠落
        headers={"X-Approval-Token": "sekret"})
    assert r.status_code == 400


def test_answer_rejects_bad_token(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    r = server.app.test_client().post(
        "/approval/answer", json={"token": "x", "key": "1"},
        headers={"X-Approval-Token": "wrong"})
    assert r.status_code == 401
