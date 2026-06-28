from unittest.mock import patch
from interactive import intent

NOW = "2026-06-28T22:00:00+09:00"


def _gemini_function_call(name, args):
    return {"candidates": [{"content": {"parts": [
        {"functionCall": {"name": name, "args": args}}
    ]}}]}


def test_calendar_intent_parsed():
    fake = _gemini_function_call("add_calendar_event", {
        "title": "歯医者", "start": "2026-06-29T14:00:00+09:00",
        "end": "2026-06-29T15:00:00+09:00", "all_day": False,
    })
    with patch("interactive.intent._call_gemini", return_value=fake):
        out = intent.parse_intent("明日14時に歯医者", NOW)
    assert out["action"] == "add_calendar_event"
    assert out["params"]["title"] == "歯医者"
    assert out["params"]["start"] == "2026-06-29T14:00:00+09:00"


def test_memo_intent_parsed():
    fake = _gemini_function_call("add_memo", {"content": "牛乳を買う", "tags": ["買い物"]})
    with patch("interactive.intent._call_gemini", return_value=fake):
        out = intent.parse_intent("牛乳買うのメモ", NOW)
    assert out["action"] == "add_memo"
    assert out["params"]["content"] == "牛乳を買う"


def test_no_function_call_is_none():
    fake = {"candidates": [{"content": {"parts": [{"text": "こんにちは!"}]}}]}
    with patch("interactive.intent._call_gemini", return_value=fake):
        out = intent.parse_intent("こんにちは", NOW)
    assert out["action"] == "none"
    assert "こんにちは" in out["message"]
