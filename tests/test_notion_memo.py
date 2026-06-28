from unittest.mock import patch, MagicMock
from interactive.actions import notion_memo


def test_add_posts_page_with_title_and_db():
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = {"url": "https://notion.so/abc"}
        return m

    with patch("interactive.actions.notion_memo.requests.post", side_effect=fake_post):
        url = notion_memo.add("牛乳を買う", tags=["買い物"])
    assert url == "https://notion.so/abc"
    assert captured["url"] == "https://api.notion.com/v1/pages"
    assert captured["json"]["parent"]["database_id"] is not None
    title = captured["json"]["properties"]["名前"]["title"][0]["text"]["content"]
    assert title == "牛乳を買う"
    assert captured["headers"]["Authorization"].startswith("Bearer ")
