#!/usr/bin/env python3
"""日記エントリと写真の永続化/取得。同日は1エントリにマージする。

保存先は data/diary/(テストは DIARY_DIR を monkeypatch で差し替える)。
ファイルシステムのみに依存。
"""
import json
from pathlib import Path

DIARY_DIR = Path(__file__).resolve().parent.parent / "data" / "diary"


def _entries_dir() -> Path:
    d = DIARY_DIR / "entries"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _entry_file(date: str) -> Path:
    return _entries_dir() / f"{date}.json"


def get(date: str):
    f = _entry_file(date)
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def _merge(old: dict, new: dict) -> dict:
    out = dict(old)
    out["body"] = (old.get("body", "") + "\n\n" + new.get("body", "")).strip()
    out["raw"] = (old.get("raw", "") + "\n\n" + new.get("raw", "")).strip()
    tags = list(old.get("tags", []))
    for t in new.get("tags", []):
        if t not in tags:
            tags.append(t)
    out["tags"] = tags
    out["photos"] = list(old.get("photos", [])) + list(new.get("photos", []))
    out["title"] = new.get("title") or old.get("title")
    out["updated"] = new.get("updated") or old.get("updated")
    return out


def save(entry: dict) -> str:
    date = entry["date"]
    existing = get(date)
    final = _merge(existing, entry) if existing else entry
    f = _entry_file(date)
    f.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(f)


def list_entries():
    d = _entries_dir()
    out = []
    for f in d.glob("*.json"):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"[WARN] diary_store list skip {f}: {e}")
    out.sort(key=lambda e: e.get("date", ""), reverse=True)
    return out


def media_path(date: str, filename: str) -> Path:
    return DIARY_DIR / "media" / date / filename


def save_photo(date: str, data: bytes, ext: str = ".jpg") -> str:
    d = DIARY_DIR / "media" / date
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob("*"))) + 1
    filename = f"{n}{ext}"
    (d / filename).write_bytes(data)
    return filename
