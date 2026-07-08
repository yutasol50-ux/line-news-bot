from unittest.mock import patch, MagicMock
from shared import line_client


def test_push_quick_reply_builds_postback_items():
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        m = MagicMock(); m.status_code = 200; m.text = "ok"
        return m

    with patch("shared.line_client.requests.post", side_effect=fake_post):
        ok = line_client.push_quick_reply(
            "承認して",
            [{"label": "Yes", "data": "approve:tok:1"},
             {"label": "却下", "data": "approve:tok:3"}],
        )
    assert ok is True
    msg = captured["json"]["messages"][0]
    assert msg["text"] == "承認して"
    items = msg["quickReply"]["items"]
    assert items[0]["action"]["type"] == "postback"
    assert items[0]["action"]["label"] == "Yes"
    assert items[0]["action"]["data"] == "approve:tok:1"
    assert items[0]["action"]["displayText"] == "Yes"
    assert len(items) == 2
