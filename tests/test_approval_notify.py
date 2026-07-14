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


def test_notify_registers_and_pushes(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_NOTIFY_LINE", "1")  # LINE点灯時の挙動を検証(.env非依存)
    server = _client(tmp_path, monkeypatch)
    with patch("interactive.server.line_client.push_quick_reply", return_value=True) as push:
        r = server.app.test_client().post(
            "/approval/notify",
            json={"pane": "%3", "cwd": "~/x", "capture": PROMPT},
            headers={"X-Approval-Token": "sekret"},
        )
    assert r.status_code == 200
    tok = r.get_json()["token"]
    from interactive import approval_store
    assert approval_store.get(tok)["pane"] == "%3"
    assert push.called
    # ボタンの data は approve:<token>:<key>
    items = push.call_args[0][1]
    assert items[0]["data"] == f"approve:{tok}:1"


def test_notify_also_triggers_pushcut(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    with patch("interactive.server.line_client.push_quick_reply", return_value=True), \
         patch("interactive.server.pushcut_client.notify", return_value=True) as pc:
        r = server.app.test_client().post(
            "/approval/notify",
            json={"pane": "%3", "cwd": "~/x", "capture": PROMPT},
            headers={"X-Approval-Token": "sekret"},
        )
    assert r.status_code == 200
    assert pc.called  # Pushcut にも通知


def test_notify_also_triggers_bark_with_icon(tmp_path, monkeypatch):
    monkeypatch.setenv("BARK_APPROVAL_ICON", "https://example.com/lock.png")
    server = _client(tmp_path, monkeypatch)
    with patch("interactive.server.line_client.push_quick_reply", return_value=True), \
         patch("interactive.server.pushcut_client.notify", return_value=True), \
         patch("interactive.server.bark_client.notify", return_value=True) as bk:
        r = server.app.test_client().post(
            "/approval/notify",
            json={"pane": "%3", "cwd": "~/x", "capture": PROMPT},
            headers={"X-Approval-Token": "sekret"},
        )
    assert r.status_code == 200
    assert bk.called  # Bark にも通知
    kwargs = bk.call_args.kwargs
    assert kwargs.get("icon") == "https://example.com/lock.png"  # 鍵アイコン
    assert kwargs.get("group") == "approval"


def test_notify_rejects_bad_token(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    r = server.app.test_client().post(
        "/approval/notify", json={"pane": "%3", "cwd": "", "capture": PROMPT},
        headers={"X-Approval-Token": "wrong"})
    assert r.status_code == 401


def test_notify_ignores_non_prompt(tmp_path, monkeypatch):
    server = _client(tmp_path, monkeypatch)
    with patch("interactive.server.line_client.push_quick_reply") as push:
        r = server.app.test_client().post(
            "/approval/notify", json={"pane": "%3", "cwd": "", "capture": "idle\n❯\n"},
            headers={"X-Approval-Token": "sekret"})
    assert r.status_code == 204
    assert not push.called


def test_notify_line_disabled_but_telegram_on(tmp_path, monkeypatch):
    """APPROVAL_NOTIFY_LINE=0 のとき LINE は呼ばず Telegram は呼ぶ。"""
    monkeypatch.setenv("APPROVAL_NOTIFY_LINE", "0")
    server = _client(tmp_path, monkeypatch)
    with patch("interactive.server.line_client.push_quick_reply") as line, \
         patch("interactive.server.telegram_client.notify", return_value=True) as tg:
        r = server.app.test_client().post(
            "/approval/notify",
            json={"pane": "%3", "cwd": "~/x", "capture": PROMPT},
            headers={"X-Approval-Token": "sekret"},
        )
    assert r.status_code == 200
    assert not line.called   # LINEは止まってる
    assert tg.called         # Telegramには飛ぶ
