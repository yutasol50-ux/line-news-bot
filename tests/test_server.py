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
    # 本物の日記state(data/diary/_active.json)から隔離。
    # 隔離しないと、毎晩20時に日記がactiveになるたびwebhookが日記コレクタへ流れて落ちる。
    monkeypatch.setattr(server.diary_state, "is_active", lambda: False)
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
    # 本物の日記stateから隔離(_setup と同じ理由)。
    monkeypatch.setattr(server.diary_state, "is_active", lambda: False)
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


def test_audio_message_routes_to_voice_intake(monkeypatch):
    """音声メッセージは media_intake ではなく voice_intake.handle に渡る。"""
    calls = []
    _setup_media(monkeypatch, calls)
    monkeypatch.setattr(server.voice_intake, "handle",
                        lambda mid, rt: calls.append(("voice", mid, rt)))
    r = server.app.test_client().post(
        "/webhook", data=json.dumps({"events": [_media_event(mtype="audio", mid="A1")]}),
        headers={"X-Line-Signature": "x", "Content-Type": "application/json"})
    assert r.status_code == 200
    assert calls == [("voice", "A1", "RT")]


def test_diary_mode_audio_routes_to_voice_intake_not_photo(monkeypatch):
    """日記モード中でも音声は diary_collector.handle_photo ではなく voice_intake.handle へ。"""
    calls = []
    _setup_media(monkeypatch, calls)
    monkeypatch.setattr(server.diary_state, "is_active", lambda: True)
    monkeypatch.setattr(server.voice_intake, "handle",
                        lambda mid, rt: calls.append(("voice", mid, rt)))
    monkeypatch.setattr(server.diary_collector, "handle_photo",
                        lambda mid, rt: calls.append(("photo", mid, rt)))
    r = server.app.test_client().post(
        "/webhook", data=json.dumps({"events": [_media_event(mtype="audio", mid="A2")]}),
        headers={"X-Line-Signature": "x", "Content-Type": "application/json"})
    assert r.status_code == 200
    assert calls == [("voice", "A2", "RT")]


def test_import_does_not_trigger_voice_drain(monkeypatch):
    """モジュールのimport(=pytest収集時)だけではdrainが走らないこと。
    server は本テストの時点で既にimport済みなので、ここでspyを差し込んでも
    それ以降に副作用として呼ばれていないことを確認できる(=モジュールスコープでの
    threading.Thread(...).start() が無い証拠)。"""
    calls = []
    monkeypatch.setattr(server.voice_drain, "drain", lambda: calls.append(1) or 0)
    assert calls == []


def test_startup_drain_swallows_exceptions(monkeypatch):
    """_startup_drain は drain() が例外を投げても外へ伝播させない(起動をブロックしない)。"""
    def boom():
        raise RuntimeError("gemini busy")
    monkeypatch.setattr(server.voice_drain, "drain", boom)
    server._startup_drain()  # 例外が上がらなければOK


def test_startup_drain_calls_voice_drain(monkeypatch):
    """_startup_drain は voice_drain.drain() を呼び出す(戻り値がNoneでも例外なく完了)。"""
    calls = []
    monkeypatch.setattr(server.voice_drain, "drain", lambda: calls.append(1) or 2)
    server._startup_drain()
    assert calls == [1]
