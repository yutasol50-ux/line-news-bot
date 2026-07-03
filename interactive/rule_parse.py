#!/usr/bin/env python3
"""Geminiを使わずに「定型の予定メッセージ」をローカルで解析する。

無料枠(1日20回)を食い潰さないための前段。日付が取れた定型文だけを担当し、
曖昧な文・日付なしの文は None を返して呼び出し側(Gemini)に委ねる。
"""
import re
from datetime import datetime, timedelta

_REL_DAYS = {
    "本日": 0, "今日": 0, "きょう": 0,
    "明日": 1, "あした": 1, "あす": 1,
    "明後日": 2, "あさって": 2,
    "明々後日": 3, "明明後日": 3, "しあさって": 3,
}
_WEEKDAYS = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}


def _resolve_md(now: datetime, mo: int, d: int) -> datetime | None:
    """M月D日 → 直近未来の日付。今年で過ぎていれば翌年に送る。"""
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for year in (now.year, now.year + 1):
        try:
            cand = base.replace(year=year, month=mo, day=d)
        except ValueError:
            return None  # 2/30 等の不正日付
        if cand.date() >= now.date():
            return cand
    return None


def _resolve_weekday(now: datetime, prefix: str | None, target: int) -> datetime:
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)
    delta = (target - base.weekday()) % 7
    if prefix == "来週":
        delta += 7 if delta else 7  # 必ず次の週へ
    elif delta == 0 and prefix != "今週":
        delta = 7  # 無印で当日曜日 → 次の同曜日(過去にしない)
    return base + timedelta(days=delta)


def _parse_date(text: str, now: datetime):
    """(datetime, (span)) を返す。見つからなければ (None, None)。"""
    for kw, delta in _REL_DAYS.items():
        m = re.search(kw, text)
        if m:
            return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=delta), m.span()
    m = re.search(r"(\d{1,2})月(\d{1,2})日?", text)
    if m:
        return _resolve_md(now, int(m.group(1)), int(m.group(2))), m.span()
    m = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", text)
    if m:
        return _resolve_md(now, int(m.group(1)), int(m.group(2))), m.span()
    m = re.search(r"(来週|今週|次の|今度の)?(月|火|水|木|金|土|日)曜日?", text)
    if m:
        return _resolve_weekday(now, m.group(1), _WEEKDAYS[m.group(2)]), m.span()
    return None, None


def _parse_time(text: str):
    """(hour, minute, span) を返す。見つからなければ (None, None, None)。"""
    m = re.search(r"(午前|午後|朝|夜|夕方)?\s*(\d{1,2})時(半|(\d{1,2})分)?", text)
    if m:
        hour = int(m.group(2))
        ampm = m.group(1)
        if m.group(3) == "半":
            minute = 30
        elif m.group(4):
            minute = int(m.group(4))
        else:
            minute = 0
        if ampm in ("午後", "夜", "夕方") and hour < 12:
            hour += 12
        if ampm == "午前" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute, m.span()
    m = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute, m.span()
    return None, None, None


def _extract_title(text: str, spans: list) -> str:
    """日時に使った部分を取り除き、前後の助詞・記号を落として件名を得る。"""
    out, last = [], 0
    for s, e in sorted(s for s in spans if s):
        out.append(text[last:s])
        last = e
    out.append(text[last:])
    title = "".join(out).strip()
    title = re.sub(r"^[\sにのはをがで、,，。・~〜\-]+", "", title)
    title = re.sub(r"[\sにのはをがで、,，。・~〜\-]+$", "", title)
    return title.strip()


def parse(text: str, now_iso: str) -> dict | None:
    """定型の予定文を解析。日付+件名が取れた時だけ dict を返す。"""
    now = datetime.fromisoformat(now_iso)
    date, date_span = _parse_date(text, now)
    if date is None:
        return None  # 日付なし → 自信なし。Geminiに任せる

    hour, minute, time_span = _parse_time(text)
    if hour is None:
        start_iso = date.strftime("%Y-%m-%dT00:00:00+09:00")
        end_iso, all_day = None, True
    else:
        start = date.replace(hour=hour, minute=minute)
        start_iso = start.strftime("%Y-%m-%dT%H:%M:00+09:00")
        end_iso = (start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:00+09:00")
        all_day = False

    title = _extract_title(text, [date_span, time_span])
    if not title:
        return None  # 日付はあるが件名不明 → Geminiに任せる

    return {"action": "add_calendar_event", "params": {
        "title": title, "start": start_iso, "end": end_iso, "all_day": all_day,
    }, "message": "", "source": "rule"}
