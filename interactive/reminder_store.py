"""リマインダー配達状態。JSON 1ファイルに delivered(event_id→発火時刻) と active。

approval_store と同じアトミック書き込み流儀。
- delivered: 一度Pushcut通知した予定id。cronが毎分再通知しないための既配達フラグ。
- active: 直近に配達した未対応の予定id。Pushcutの固定ボタン(event_id無し)がこれを操作する。
スヌーズ時は clear で delivered を外し、予定を先へ動かせば次の到来時に再発火する。
"""
import json
import os
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "reminders" / "state.json"


def _path() -> Path:
    return Path(os.environ.get("REMINDER_STORE", str(_DEFAULT)))


def _load() -> dict:
    p = _path()
    if not p.exists():
        return {"delivered": {}, "active": None}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        d.setdefault("delivered", {})
        d.setdefault("active", None)
        return d
    except (json.JSONDecodeError, OSError):
        return {"delivered": {}, "active": None}


def _save(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def mark_delivered(event_id: str, *, now_iso: str) -> None:
    data = _load()
    data["delivered"][event_id] = now_iso
    data["active"] = event_id
    _save(data)


def is_delivered(event_id: str) -> bool:
    return event_id in _load()["delivered"]


def get_active():
    return _load().get("active")


def clear(event_id: str) -> None:
    data = _load()
    data["delivered"].pop(event_id, None)
    if data.get("active") == event_id:
        data["active"] = None
    _save(data)
