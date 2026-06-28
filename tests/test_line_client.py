from unittest.mock import patch, MagicMock
from shared import line_client


def test_reply_posts_to_reply_endpoint():
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        m = MagicMock()
        m.status_code = 200
        m.text = "{}"
        return m

    with patch("shared.line_client.requests.post", side_effect=fake_post):
        ok = line_client.reply("RTOKEN", "やったよ")
    assert ok is True
    assert captured["url"] == "https://api.line.me/v2/bot/message/reply"
    assert captured["json"]["replyToken"] == "RTOKEN"
    assert captured["json"]["messages"][0]["text"] == "やったよ"
