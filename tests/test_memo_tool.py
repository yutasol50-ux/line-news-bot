import json
import hermes_tools.memo_tool as mt


def test_memo_add_ok(monkeypatch):
    monkeypatch.setattr(mt, "_run",
                        lambda cmd, payload: {"ok": True, "url": "https://notion/x"})
    out = json.loads(mt.memo_add("牛乳を買う", tags=["買い物"]))
    assert out["ok"] is True and out["url"] == "https://notion/x"
