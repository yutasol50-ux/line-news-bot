#!/usr/bin/env python3
"""intent結果をアクションに振り分け、LINE返信用の日本語文を返す。"""
from interactive import intent
from interactive.actions import calendar_add, notion_memo


def _fmt_dt(iso: str | None, all_day: bool) -> str:
    if not iso:
        return ""
    return iso[:10] if all_day else iso[:16].replace("T", " ")


def handle(text: str, now_iso: str) -> str:
    try:
        result = intent.parse_intent(text, now_iso)
    except Exception as e:
        print(f"[ERROR] intent: {e}")
        return "ごめん、ちょっと調子が悪いみたい。もう一回送ってくれる?"

    action = result["action"]
    p = result["params"]
    try:
        if action == "add_calendar_event":
            calendar_add.add(title=p["title"], start_iso=p["start"],
                             end_iso=p.get("end"), all_day=p["all_day"])
            return f"📅 {_fmt_dt(p['start'], p['all_day'])} {p['title']} を登録したよ"
        if action == "add_memo":
            notion_memo.add(content=p["content"], tags=p.get("tags") or None)
            tag = f"({'・'.join(p['tags'])})" if p.get("tags") else ""
            return f"📝 メモに追加したよ{tag}:{p['content']}"
        return result.get("message") or "うん、了解!"
    except Exception as e:
        print(f"[ERROR] action {action}: {e}")
        target = "カレンダー" if action == "add_calendar_event" else "メモ"
        return f"⚠️ {target}の登録に失敗しちゃった。後で確認してね。"
