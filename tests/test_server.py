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


def test_webhook_dispatches_and_replies(monkeypatch):
    monkeypatch.setattr(server, "CHANNEL_SECRET", SECRET)
    replied = {}
    monkeypatch.setattr(server, "verify_signature", lambda b, s: True)
    monkeypatch.setattr(server.dispatch, "handle", lambda t, n: "OK登録")
    monkeypatch.setattr(server.line_client, "reply",
                        lambda rt, msg: replied.update(rt=rt, msg=msg) or True)
    client = server.app.test_client()
    payload = {"events": [{"type": "message", "replyToken": "RT",
               "message": {"type": "text", "text": "明日歯医者"}}]}
    r = client.post("/webhook", data=json.dumps(payload),
                    headers={"X-Line-Signature": "x", "Content-Type": "application/json"})
    assert r.status_code == 200
    assert replied["msg"] == "OK登録"
