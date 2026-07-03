from interactive import rule_parse

NOW = "2026-06-29T23:30:00+09:00"  # 月曜


def _p(text):
    return rule_parse.parse(text, NOW)


def test_absolute_date_all_day():
    out = _p("7月1日サッカー")
    assert out["action"] == "add_calendar_event"
    assert out["params"]["title"] == "サッカー"
    assert out["params"]["start"] == "2026-07-01T00:00:00+09:00"
    assert out["params"]["all_day"] is True


def test_tomorrow_all_day():
    out = _p("明日サッカー")
    assert out["params"]["start"] == "2026-06-30T00:00:00+09:00"
    assert out["params"]["title"] == "サッカー"
    assert out["params"]["all_day"] is True


def test_today():
    assert _p("今日歯医者")["params"]["start"] == "2026-06-29T00:00:00+09:00"


def test_day_after_tomorrow():
    assert _p("明後日サッカー")["params"]["start"] == "2026-07-01T00:00:00+09:00"


def test_slash_date():
    assert _p("7/1サッカー")["params"]["start"] == "2026-07-01T00:00:00+09:00"


def test_with_time_and_particle():
    out = _p("明日14時に歯医者")
    assert out["params"]["title"] == "歯医者"
    assert out["params"]["start"] == "2026-06-30T14:00:00+09:00"
    assert out["params"]["end"] == "2026-06-30T15:00:00+09:00"
    assert out["params"]["all_day"] is False


def test_time_half():
    assert _p("明日15時半に会議")["params"]["start"] == "2026-06-30T15:30:00+09:00"


def test_time_colon():
    assert _p("明日9:05に通院")["params"]["start"] == "2026-06-30T09:05:00+09:00"


def test_afternoon():
    assert _p("明日午後3時に打ち合わせ")["params"]["start"] == "2026-06-30T15:00:00+09:00"


def test_past_month_rolls_to_next_year():
    # 1月5日 は 6/29 時点で過去 → 翌年
    assert _p("1月5日帰省")["params"]["start"] == "2027-01-05T00:00:00+09:00"


def test_weekday_next_occurrence():
    # 月曜(今日)無印 → 次の月曜 7/6
    assert _p("月曜サッカー")["params"]["start"] == "2026-07-06T00:00:00+09:00"


def test_weekday_this_week():
    # 今週水曜 → 7/1
    assert _p("今週水曜サッカー")["params"]["start"] == "2026-07-01T00:00:00+09:00"


def test_no_date_returns_none():
    assert _p("こんにちは") is None
    assert _p("牛乳を買う") is None


def test_date_without_title_returns_none():
    # 件名が取れない → Geminiに委ねる
    assert _p("明日") is None


def test_invalid_date_returns_none():
    assert _p("2月30日サッカー") is None
