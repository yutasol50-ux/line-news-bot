"""
Cohere APIリクエスト数管理モジュール
1日の上限900回、残り100回で警告、超過時は停止
翌日0時(JST)にリセット
"""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
COUNTER_FILE = Path(__file__).parent / "data" / "request_counter.json"
DAILY_LIMIT = int(os.getenv("DAILY_REQUEST_LIMIT", "900"))
WARNING_THRESHOLD = int(os.getenv("WARNING_THRESHOLD", "100"))


def _today_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def _load() -> dict:
    COUNTER_FILE.parent.mkdir(exist_ok=True)
    if COUNTER_FILE.exists():
        try:
            return json.loads(COUNTER_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"date": _today_jst(), "count": 0}


def _save(data: dict) -> None:
    COUNTER_FILE.parent.mkdir(exist_ok=True)
    COUNTER_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_count() -> int:
    """今日の使用回数を取得"""
    data = _load()
    if data["date"] != _today_jst():
        return 0
    return data["count"]


def get_remaining() -> int:
    """残りリクエスト数を取得"""
    return max(0, DAILY_LIMIT - get_count())


def increment(n: int = 1) -> dict:
    """
    カウントをn増やす
    Returns: {"ok": bool, "count": int, "remaining": int, "warning": bool, "limit_reached": bool}
    """
    data = _load()
    today = _today_jst()

    # 日付が変わっていたらリセット
    if data["date"] != today:
        data = {"date": today, "count": 0}

    data["count"] += n
    _save(data)

    remaining = max(0, DAILY_LIMIT - data["count"])
    warning = remaining <= WARNING_THRESHOLD and remaining > 0
    limit_reached = data["count"] >= DAILY_LIMIT

    return {
        "ok": not limit_reached,
        "count": data["count"],
        "remaining": remaining,
        "warning": warning,
        "limit_reached": limit_reached,
    }


def can_request(n: int = 1) -> bool:
    """n回リクエストできるか確認（カウントは増やさない）"""
    return get_remaining() >= n


def reset() -> None:
    """カウンターを強制リセット（手動用）"""
    data = {"date": _today_jst(), "count": 0}
    _save(data)
    print(f"[RequestCounter] リセット完了: {data}")


def status() -> str:
    """ステータス文字列を返す"""
    count = get_count()
    remaining = get_remaining()
    today = _today_jst()
    bar_filled = int(count / DAILY_LIMIT * 20)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    pct = count / DAILY_LIMIT * 100
    return (
        f"**Cohere APIリクエスト状況** ({today})\n"
        f"`[{bar}]` {pct:.1f}%\n"
        f"使用: {count}/{DAILY_LIMIT} | 残り: {remaining}"
    )


if __name__ == "__main__":
    print(status())
