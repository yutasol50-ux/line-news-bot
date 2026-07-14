"""/approval/answer_text: Telegramポーラー用のテキスト承認注入エンドポイント。"""
import importlib
from unittest.mock import patch


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_TOKEN", "sekret")
    monkeypatch.setenv("APPROVAL_STORE", str(tmp_path / "p.json"))
    from interactive import server
    importlib.reload(server)
    server.app.config["TESTING"] = True
    return server


PROMPT = "Do you want to proceed?\n❯ 1. Yes\n  2. Yes, and don't ask again\n  3. No (esc)\n"


def _register(server, token="tk1"):
    server.approval_store.register(
        "%3", "~/x", "Do you want to proceed?",
        [{"key": "1", "label": "Yes"}, {"key": "3", "label": "No"}],
        now_iso="2026-07-13T10:00:00", token=token,
    )


def test_answer_text_ok_injects(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    _register(server)
    with patch("interactive.server.tmux_inject.capture", return_value=PROMPT), \
         patch("interactive.server.tmux_inject.send_key", return_value=True) as sk:
        r = server.app.test_client().post(
            "/approval/answer_text", json={"text": "OK"},
            headers={"X-Approval-Token": "sekret"},
        )
    assert r.status_code == 200
    body = r.get_json()
    assert body["handled"] is True
    assert body["status"] == "done"
    assert "✅" in body["message"]
    assert sk.called
    assert sk.call_args[0] == ("%3", "1")


def test_answer_text_no_pending(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    r = server.app.test_client().post(
        "/approval/answer_text", json={"text": "OK"},
        headers={"X-Approval-Token": "sekret"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["handled"] is False


def test_answer_text_bad_token(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    _register(server)
    r = server.app.test_client().post(
        "/approval/answer_text", json={"text": "OK"},
        headers={"X-Approval-Token": "wrong"},
    )
    assert r.status_code == 401


def test_answer_text_missing_token_header(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    _register(server)
    r = server.app.test_client().post(
        "/approval/answer_text", json={"text": "OK"},
    )
    assert r.status_code == 401


def test_answer_text_missing_text_is_400(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    _register(server)
    r = server.app.test_client().post(
        "/approval/answer_text", json={},
        headers={"X-Approval-Token": "sekret"},
    )
    assert r.status_code == 400


def test_answer_text_no_server_token_configured(tmp_path, monkeypatch):
    # delenvだと load_dotenv(override=False) が .env の値で埋め戻してしまうため、
    # 空文字を明示セットして「未設定」を安定に再現する。
    monkeypatch.setenv("APPROVAL_TOKEN", "")
    monkeypatch.setenv("APPROVAL_STORE", str(tmp_path / "p.json"))
    from interactive import server
    importlib.reload(server)
    server.app.config["TESTING"] = True
    r = server.app.test_client().post(
        "/approval/answer_text", json={"text": "OK"},
        headers={"X-Approval-Token": "whatever"},
    )
    assert r.status_code == 503


def test_answer_text_non_approval_text_ignored(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    _register(server)
    r = server.app.test_client().post(
        "/approval/answer_text", json={"text": "こんにちは"},
        headers={"X-Approval-Token": "sekret"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["handled"] is False
