"""/capture エンドポイント(Apple Watch ショートカット用・署名不要・トークン認証)のテスト。"""
import json

import interactive.server as server


def _client():
    server.app.config["TESTING"] = True
    return server.app.test_client()


def _patch_brain(monkeypatch, route="inline"):
    """research_async.handle_capture を差し替え、呼ばれた引数を記録し (reply, route) を返す。"""
    seen = {}

    def _handle_capture(t, sid="line-owner"):
        seen["args"] = (t, sid)
        return f"H:{t}", route

    monkeypatch.setattr(server.research_async, "handle_capture", staticmethod(_handle_capture))
    return seen


def _patch_line(monkeypatch):
    """line_client.push を差し替え、LINEへ流した文言を記録する(本物のAPIを叩かせない)。"""
    pushed = []

    def _push(text):
        pushed.append(text)
        return True

    monkeypatch.setattr(server, "line_client",
                        type("L", (), {"push": staticmethod(_push)}))
    return pushed


def test_capture_ok_token_in_body(monkeypatch):
    monkeypatch.setenv("CAPTURE_TOKEN", "secret123")
    seen = _patch_brain(monkeypatch)
    _patch_line(monkeypatch)
    r = _client().post("/capture", json={"text": "牛乳買う", "token": "secret123"})
    assert r.status_code == 200
    assert r.get_json()["reply"] == "H:牛乳買う"
    # LINE と同じ会話部屋(line-owner)を共有する。
    assert seen["args"] == ("牛乳買う", "line-owner")


def test_capture_mirrors_exchange_to_line(monkeypatch):
    """Watchの発言と返事を LINE トークへ流し、会話の記録を残す。"""
    monkeypatch.setenv("CAPTURE_TOKEN", "secret123")
    _patch_brain(monkeypatch)
    pushed = _patch_line(monkeypatch)
    r = _client().post("/capture", json={"text": "牛乳買う", "token": "secret123"})
    assert r.status_code == 200
    assert len(pushed) == 1
    assert "牛乳買う" in pushed[0]      # 喋った内容
    assert "H:牛乳買う" in pushed[0]    # Hermesの返事
    assert "Watch" in pushed[0]         # Watch由来と分かる印


def test_capture_ok_token_in_header(monkeypatch):
    monkeypatch.setenv("CAPTURE_TOKEN", "secret123")
    _patch_brain(monkeypatch)
    _patch_line(monkeypatch)
    r = _client().post(
        "/capture",
        data=json.dumps({"text": "やあ"}),
        headers={"Content-Type": "application/json", "X-Capture-Token": "secret123"},
    )
    assert r.status_code == 200
    assert r.get_json()["reply"] == "H:やあ"


def test_capture_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("CAPTURE_TOKEN", "secret123")
    _patch_brain(monkeypatch)
    r = _client().post("/capture", json={"text": "やあ", "token": "WRONG"})
    assert r.status_code == 401


def test_capture_rejects_empty_text(monkeypatch):
    monkeypatch.setenv("CAPTURE_TOKEN", "secret123")
    _patch_brain(monkeypatch)
    r = _client().post("/capture", json={"text": "   ", "token": "secret123"})
    assert r.status_code == 400


def test_capture_500_guard_when_token_unset(monkeypatch):
    """サーバ側 CAPTURE_TOKEN 未設定なら、誰も入れないよう 503 で閉じる。"""
    monkeypatch.delenv("CAPTURE_TOKEN", raising=False)
    _patch_brain(monkeypatch)
    r = _client().post("/capture", json={"text": "やあ", "token": ""})
    assert r.status_code == 503
