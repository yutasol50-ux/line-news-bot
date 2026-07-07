"""server: 日記モード中は diary_collector へ振り分け、通常Hermesへ流さない。
また「日記」テキストで日記モードを手動起動できる。
"""
import json
import interactive.server as srv


def _post(client, text=None, mtype="text", mid="MID"):
    msg = {"type": mtype}
    if text is not None:
        msg["text"] = text
    if mtype != "text":
        msg["id"] = mid
    body = {"events": [{"type": "message", "message": msg,
                        "replyToken": "RT", "webhookEventId": "E1"}]}
    raw = json.dumps(body).encode()
    # 重複判定の状態をテスト間でリセット(同じ webhookEventId="E1" を使い回すため)
    srv._seen_ids.clear()
    srv._seen_set.clear()
    return client.post("/webhook", data=raw,
                       headers={"X-Line-Signature": "sig",
                                "Content-Type": "application/json"})


def test_diary_active_text_goes_to_collector(monkeypatch):
    monkeypatch.setattr(srv, "verify_signature", lambda b, s: True)
    monkeypatch.setattr(srv, "_spawn", lambda fn: fn())     # 同期実行
    monkeypatch.setattr(srv.diary_state, "is_active", lambda: True)
    called = {}
    monkeypatch.setattr(srv.diary_collector, "handle_text",
                        lambda t, rt, **k: called.setdefault("text", (t, rt)))
    # 通常Hermesは呼ばれてはいけない
    monkeypatch.setattr(srv, "_process",
                        lambda *a, **k: called.setdefault("hermes", True))
    r = _post(srv.app.test_client(), text="日記の中身")
    assert r.status_code == 200
    assert called["text"] == ("日記の中身", "RT")
    assert "hermes" not in called


def test_diary_inactive_uses_normal_path(monkeypatch):
    monkeypatch.setattr(srv, "verify_signature", lambda b, s: True)
    monkeypatch.setattr(srv, "_spawn", lambda fn: fn())
    monkeypatch.setattr(srv.diary_state, "is_active", lambda: False)
    called = {}
    monkeypatch.setattr(srv, "_process", lambda *a, **k: called.setdefault("hermes", True))
    r = _post(srv.app.test_client(), text="普通の質問")
    assert r.status_code == 200
    assert called.get("hermes") is True


def test_diary_active_photo_goes_to_collector(monkeypatch):
    monkeypatch.setattr(srv, "verify_signature", lambda b, s: True)
    monkeypatch.setattr(srv, "_spawn", lambda fn: fn())
    monkeypatch.setattr(srv.diary_state, "is_active", lambda: True)
    called = {}
    monkeypatch.setattr(srv.diary_collector, "handle_photo",
                        lambda mid, rt, **k: called.setdefault("photo", (mid, rt)))
    monkeypatch.setattr(srv.media_intake, "handle",
                        lambda *a, **k: called.setdefault("intake", True))
    r = _post(srv.app.test_client(), mtype="image", mid="PID")
    assert r.status_code == 200
    assert called["photo"] == ("PID", "RT")
    assert "intake" not in called


def test_manual_diary_keyword_starts(monkeypatch):
    monkeypatch.setattr(srv, "verify_signature", lambda b, s: True)
    monkeypatch.setattr(srv, "_spawn", lambda fn: fn())
    monkeypatch.setattr(srv.diary_state, "is_active", lambda: False)
    called = {}
    monkeypatch.setattr(srv.diary_collector, "start_manual",
                        lambda rt, **k: called.setdefault("start_manual", rt))
    monkeypatch.setattr(srv, "_process",
                        lambda *a, **k: called.setdefault("hermes", True))
    r = _post(srv.app.test_client(), text="日記")
    assert r.status_code == 200
    assert called["start_manual"] == "RT"
    assert "hermes" not in called


def test_normal_text_when_inactive_does_not_start_manual(monkeypatch):
    monkeypatch.setattr(srv, "verify_signature", lambda b, s: True)
    monkeypatch.setattr(srv, "_spawn", lambda fn: fn())
    monkeypatch.setattr(srv.diary_state, "is_active", lambda: False)
    called = {}
    monkeypatch.setattr(srv, "_process",
                        lambda *a, **k: called.setdefault("hermes", True))
    monkeypatch.setattr(srv.diary_collector, "start_manual",
                        lambda rt, **k: called.setdefault("start_manual", rt))
    r = _post(srv.app.test_client(), text="こんにちは")
    assert r.status_code == 200
    assert called.get("hermes") is True
    assert "start_manual" not in called
