"""承認待ち中のテキスト「OK」等をtmux注入に横取りする(_try_answer_approval)テスト。"""
import interactive.server as server


def _sync_spawn(monkeypatch):
    monkeypatch.setattr(server, "_spawn", lambda fn: fn())  # スレッドを同期実行


def _pending(monkeypatch, entries):
    monkeypatch.setattr(server.approval_store, "pending_entries", lambda: entries)


ENTRY = {"token": "tk1", "created": "2026-07-12T10:00:00",
         "choices": [{"key": "1", "label": "Yes"},
                     {"key": "3", "label": "No, and tell Claude what to do differently"}]}


def test_ok_injects_yes(monkeypatch):
    _sync_spawn(monkeypatch)
    _pending(monkeypatch, [ENTRY])
    calls, replies = [], []
    monkeypatch.setattr(server, "_resolve_and_inject",
                        lambda tok, key: calls.append((tok, key)) or ("done", "✅ 送信"))
    monkeypatch.setattr(server.line_client, "reply", lambda rt, m: replies.append(m))
    handled = server._try_answer_approval("OK", "rtoken")
    assert handled is True
    assert calls == [("tk1", "1")]        # Yes=1 を注入
    assert replies == ["✅ 送信"]


def test_yamete_injects_no(monkeypatch):
    _sync_spawn(monkeypatch)
    _pending(monkeypatch, [ENTRY])
    calls = []
    monkeypatch.setattr(server, "_resolve_and_inject",
                        lambda tok, key: calls.append((tok, key)) or ("done", "却下"))
    monkeypatch.setattr(server.line_client, "reply", lambda rt, m: None)
    assert server._try_answer_approval("やめて", "rtoken") is True
    assert calls == [("tk1", "3")]        # No系=3


def test_no_pending_returns_false(monkeypatch):
    _pending(monkeypatch, [])
    assert server._try_answer_approval("OK", "rtoken") is False


def test_normal_chat_not_intercepted(monkeypatch):
    _pending(monkeypatch, [ENTRY])
    # 承認待ちでも、承認語でない普通の文はHermesへ回す(False)
    assert server._try_answer_approval("予定教えて", "rtoken") is False
