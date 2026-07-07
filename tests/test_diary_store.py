"""diary_store: 日記エントリと写真の永続化。同日はマージ。"""
import json
from interactive import diary_store as ds


def _entry(date="2026-07-07", **over):
    e = {"date": date, "title": "テスト", "tags": ["疲れ"], "body": "本文",
         "raw": "げんぶん", "photos": [], "created": "t0", "updated": "t0"}
    e.update(over)
    return e


def test_save_and_get_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "DIARY_DIR", tmp_path)
    ds.save(_entry())
    got = ds.get("2026-07-07")
    assert got["body"] == "本文"
    assert got["raw"] == "げんぶん"
    assert got["tags"] == ["疲れ"]


def test_same_day_merges(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "DIARY_DIR", tmp_path)
    ds.save(_entry(body="午前の分", raw="あさ", tags=["疲れ"]))
    ds.save(_entry(body="夜の追記", raw="よる", tags=["嬉しい"], title="夜"))
    got = ds.get("2026-07-07")
    assert "午前の分" in got["body"] and "夜の追記" in got["body"]
    assert "あさ" in got["raw"] and "よる" in got["raw"]
    assert set(got["tags"]) == {"疲れ", "嬉しい"}   # 重複排除の和
    assert got["title"] == "夜"                     # 新しい方


def test_list_is_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "DIARY_DIR", tmp_path)
    ds.save(_entry(date="2026-07-05"))
    ds.save(_entry(date="2026-07-07"))
    dates = [e["date"] for e in ds.list_entries()]
    assert dates == ["2026-07-07", "2026-07-05"]


def test_save_photo_returns_filename_and_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "DIARY_DIR", tmp_path)
    f1 = ds.save_photo("2026-07-07", b"JPEGDATA")
    f2 = ds.save_photo("2026-07-07", b"JPEGDATA2")
    assert f1 == "1.jpg" and f2 == "2.jpg"
    assert ds.media_path("2026-07-07", "1.jpg").read_bytes() == b"JPEGDATA"
