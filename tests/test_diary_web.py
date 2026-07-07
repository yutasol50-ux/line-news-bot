"""diary_web: 日記の本棚ページ。テーブルでなく広いカードで見せる。"""
from interactive import diary_web
from interactive import diary_store
from flask import Flask


def _client(monkeypatch, entries):
    monkeypatch.setattr(diary_store, "list_entries", lambda: entries)
    app = Flask(__name__)
    app.register_blueprint(diary_web.bp)
    return app.test_client()


def test_list_renders_entries(monkeypatch):
    c = _client(monkeypatch, [
        {"date": "2026-07-07", "title": "当務の日", "tags": ["疲れ"],
         "body": "今日は当務だった。", "photos": [{"file": "1.jpg", "caption": "電車"}]},
    ])
    html = c.get("/diary").get_data(as_text=True)
    assert "当務の日" in html
    assert "2026-07-07" in html
    assert "疲れ" in html
    assert "今日は当務だった。" in html
    assert "/diary/media/2026-07-07/1.jpg" in html   # 写真サムネのsrc


def test_empty_state(monkeypatch):
    c = _client(monkeypatch, [])
    html = c.get("/diary").get_data(as_text=True)
    assert c.get("/diary").status_code == 200
    assert "まだ" in html          # 空状態の案内


def test_missing_media_is_404(monkeypatch, tmp_path):
    monkeypatch.setattr(diary_store, "DIARY_DIR", tmp_path)
    c = _client(monkeypatch, [])
    assert c.get("/diary/media/2026-07-07/nope.jpg").status_code == 404
