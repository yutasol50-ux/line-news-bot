"""承認保留箱。JSON 1ファイルに token→エントリ。アトミック書き込み。"""
import json
import os
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "approvals" / "pending.json"


def _path() -> Path:
    return Path(os.environ.get("APPROVAL_STORE", str(_DEFAULT)))


def _load() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)  # アトミック置換


def register(pane, cwd, question, choices, *, now_iso, token) -> None:
    data = _load()
    data[token] = {
        "token": token, "pane": pane, "cwd": cwd, "question": question,
        "choices": choices, "created": now_iso, "state": "pending",
    }
    _save(data)


def get(token: str):
    e = _load().get(token)
    if e and e.get("state") == "pending":
        return e
    return None


def resolve(token: str) -> None:
    data = _load()
    if token in data:
        data[token]["state"] = "done"
        _save(data)


def pending_panes() -> list:
    return [e["pane"] for e in _load().values() if e.get("state") == "pending"]


def pending_entries() -> list:
    """pending なエントリを丸ごと返す(token/question/choices/pane/cwd/created 込み)。"""
    return [e for e in _load().values() if e.get("state") == "pending"]
