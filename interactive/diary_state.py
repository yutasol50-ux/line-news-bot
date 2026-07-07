#!/usr/bin/env python3
"""日記モードの下書き状態機械。毎回ファイルから読み書きし、サーバ再起動でも消えない。

状態は単一JSON(_active.json)。純粋(Haiku/LINEを呼ばない)。
"""
import json
import os
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "diary" / "_active.json"


def _load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"active": False}


def _save(s: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)          # アトミック置換(プロセス毎tmpで衝突回避)


def start(date: str, *, now: str) -> None:
    _save({"active": True, "phase": "collecting", "date": date,
           "raw_parts": [], "photos": [], "composed": None,
           "started": now, "last": now})


def is_active() -> bool:
    return bool(_load().get("active"))


def phase() -> str:
    return _load().get("phase", "collecting")


def date():
    return _load().get("date")


def append_text(text: str, *, now: str) -> None:
    s = _load()
    s.setdefault("raw_parts", []).append(text)
    s["last"] = now
    _save(s)


def append_photo(file: str, caption: str, *, now: str) -> None:
    s = _load()
    s.setdefault("photos", []).append({"file": file, "caption": caption})
    s["last"] = now
    _save(s)


def raw() -> str:
    return "\n".join(_load().get("raw_parts", []))


def captions():
    return [p.get("caption", "") for p in _load().get("photos", [])]


def photos():
    return list(_load().get("photos", []))


def set_confirming(composed: dict, *, now: str) -> None:
    s = _load()
    s["phase"] = "confirming"
    s["composed"] = composed
    s["last"] = now
    _save(s)


def composed():
    return _load().get("composed")


def last():
    return _load().get("last")


def clear() -> None:
    _save({"active": False})


def reopen(*, now: str) -> None:
    """confirming等から collecting に戻す。下書き(raw_parts/photos)は保持する。"""
    s = _load()
    s["phase"] = "collecting"
    s["composed"] = None
    s["last"] = now
    _save(s)
