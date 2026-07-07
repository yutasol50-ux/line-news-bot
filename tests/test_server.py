import base64
import hashlib
import hmac
import json
import interactive.server as server

SECRET = "testsecret"


def _sign(body: bytes) -> str:
    return base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()


def test_verify_signature_ok(monkeypatch):
    monkeypatch.setattr(server, "CHANNEL_SECRET", SECRET)
    body = b'{"events":[]}'
    assert server.verify_signature(body, _sign(body)) is True


def test_verify_signature_ng(monkeypatch):
    monkeypatch.setattr(server, "CHANNEL_SECRET", SECRET)
    assert server.verify_signature(b'{"events":[]}', "wrong") is False


def _setup(monkeypatch, calls):
    """共通: 署名OK・同期実行・dispatch/replyを記録するスタブを仕込む。"""
    monkeypatch.setattr(server, "CHANNEL_SECRET", SECRET)
    monkeypatch.setattr(server, "verify_signature", lambda b, s: True)
    # _spawn を同期実行に差し替え(バックグラウンドスレッドだと判定が不安定なため)
    monkeypatch.setattr(server, "_spawn", lambda fn: fn())
    monkeypatch.setattr(server.dispatch, "handle",
                        lambda t, n: calls.append(t) or "OK登録")
    monkeypatch.setattr(server.line_client, "reply", lambda rt, msg: True)
    # 重複判定の状態をテスト間でリセット
    server._seen_ids.clear()
    server._seen_set.clear()


def _post(client, events):
    return client.post("/webhook", data=json.dumps({"events": events}),
                       headers={"X-Line-Signature": "x", "Content-Type": "application/json"})


def _event(text="明日歯医者", event_id="E1", redelivery=False, reply_token="RT"):
    return {"type": "message", "replyToken": reply_token, "webhookEventId": event_id,
            "deliveryContext": {"isRedelivery": redelivery},
            "message": {"type": "text", "text": text}}


def test_webhook_dispatches_and_replies(monkeypatch):
    calls = []
    _setup(monkeypatch, calls)
    r = _post(server.app.test_client(), [_event()])
    assert r.status_code == 200
    assert calls == ["明日歯医者"]


def test_duplicate_event_id_processed_once(monkeypatch):
    """同じ webhookEventId が再送されても処理は1回だけ(多重登録バグの再現)。"""
    calls = []
    _setup(monkeypatch, calls)
    client = server.app.test_client()
    _post(client, [_event(event_id="DUP")])
    _post(client, [_event(event_id="DUP")])
    assert calls == ["明日歯医者"]


def test_redelivery_of_unseen_event_is_processed(monkeypatch):
    """未処理イベントの再送(isRedelivery=true)は捨てず処理する(無反応バグ防止)。"""
    calls = []
    _setup(monkeypatch, calls)
    r = _post(server.app.test_client(), [_event(event_id="R1", redelivery=True)])
    assert r.status_code == 200
    assert calls == ["明日歯医者"]


def test_redelivery_of_seen_event_is_skipped(monkeypatch):
    """一度処理したイベントの再送は重複排除で弾く(多重登録防止)。"""
    calls = []
    _setup(monkeypatch, calls)
    client = server.app.test_client()
    _post(client, [_event(event_id="R2")])
    _post(client, [_event(event_id="R2", redelivery=True)])
    assert calls == ["明日歯医者"]


def _setup_media(monkeypatch, calls):
    """署名OK・同期spawn・media_intake.handleを記録するスタブ。"""
    monkeypatch.setattr(server, "CHANNEL_SECRET", SECRET)
    monkeypatch.setattr(server, "verify_signature", lambda b, s: True)
    monkeypatch.setattr(server, "_spawn", lambda fn: fn())
    monkeypatch.setattr(server.media_intake, "handle",
                        lambda mid, kind, rt: calls.append((mid, kind, rt)))
    server._seen_ids.clear()
    server._seen_set.clear()


def _media_event(mtype="image", mid="M1", event_id="E9", reply_token="RT",
                 file_name=None):
    msg = {"type": mtype, "id": mid}
    if file_name:
        msg["fileName"] = file_name
    return {"type": "message", "replyToken": reply_token, "webhookEventId": event_id,
            "deliveryContext": {"isRedelivery": False}, "message": msg}


def test_webhook_routes_image_to_media_intake(monkeypatch):
    calls = []
    _setup_media(monkeypatch, calls)
    r = _post(server.app.test_client(), [_media_event(mtype="image", mid="IMG1")])
    assert r.status_code == 200
    assert calls == [("IMG1", "image", "RT")]


def test_webhook_routes_file_to_media_intake(monkeypatch):
    calls = []
    _setup_media(monkeypatch, calls)
    r = _post(server.app.test_client(),
              [_media_event(mtype="file", mid="F1", file_name="請求書.pdf")])
    assert r.status_code == 200
    assert calls == [("F1", "file", "RT")]


def test_webhook_ignores_audio(monkeypatch):
    calls = []
    _setup_media(monkeypatch, calls)
    r = _post(server.app.test_client(), [_media_event(mtype="audio", mid="A1")])
    assert r.status_code == 200
    assert calls == []                         # 音声は未対応(スコープ外)
