from unittest.mock import patch, MagicMock
import requests
from interactive import intent

NOW = "2026-06-28T22:00:00+09:00"


def _resp(status, json_body=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body or {}
    r.raise_for_status.side_effect = (
        requests.HTTPError(f"{status}") if status >= 400 else None
    )
    return r


def test_call_gemini_retries_on_503_then_succeeds():
    ok = _resp(200, {"candidates": []})
    posts = [_resp(503), _resp(503), ok]
    with patch("interactive.intent.requests.post", side_effect=posts) as p, \
         patch("interactive.intent.time.sleep"):
        out = intent._call_gemini({"x": 1})
    assert out == {"candidates": []}
    assert p.call_count == 3


def test_call_gemini_retries_on_timeout_then_succeeds():
    ok = _resp(200, {"candidates": []})
    side = [requests.Timeout("read timed out"), ok]
    with patch("interactive.intent.requests.post", side_effect=side), \
         patch("interactive.intent.time.sleep"):
        out = intent._call_gemini({"x": 1})
    assert out == {"candidates": []}


def test_call_gemini_gives_up_after_max_retries():
    with patch("interactive.intent.requests.post", return_value=_resp(503)), \
         patch("interactive.intent.time.sleep"):
        try:
            intent._call_gemini({"x": 1})
            assert False, "should have raised"
        except requests.HTTPError:
            pass


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


def test_rule_path_skips_gemini():
    # 定型文はローカルで処理し、Geminiを一切呼ばない(無料枠を消費しない)
    with patch("interactive.intent._call_gemini") as g:
        out = intent.parse_intent("7月1日サッカー", NOW)
    assert out["action"] == "add_calendar_event"
    assert out["params"]["title"] == "サッカー"
    g.assert_not_called()


def test_gemini_failure_returns_quota_hint():
    # ルールで拾えない文 + Gemini不可 → 諦めて定型を促す案内を返す(例外を投げない)
    with patch("interactive.intent._call_gemini", side_effect=requests.HTTPError("429")):
        out = intent.parse_intent("なんかいい感じにやっといて", NOW)
    assert out["action"] == "none"
    assert "登録できる" in out["message"]


def test_no_function_call_is_none():
    fake = {"candidates": [{"content": {"parts": [{"text": "こんにちは!"}]}}]}
    with patch("interactive.intent._call_gemini", return_value=fake):
        out = intent.parse_intent("こんにちは", NOW)
    assert out["action"] == "none"
    assert "こんにちは" in out["message"]
