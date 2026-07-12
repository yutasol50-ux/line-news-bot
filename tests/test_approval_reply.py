from interactive import approval_reply as ar

CHOICES = [
    {"key": "1", "label": "Yes"},
    {"key": "2", "label": "Yes, and don't ask again"},
    {"key": "3", "label": "No, and tell Claude what to do differently"},
]


def test_classify_yes():
    for t in ["OK", "ok", "おけ", "オーケー", "はい", "いいよ", "進めて", "yes", "うん", "y"]:
        assert ar.classify(t) == "yes", t


def test_classify_no():
    for t in ["no", "だめ", "やめて", "却下", "いいえ", "ストップ"]:
        assert ar.classify(t) == "no", t


def test_classify_none_for_normal_chat():
    for t in ["予定教えて", "牛乳メモして", "ありがとう", "今日は暑いね"]:
        assert ar.classify(t) is None, t


def test_yes_maps_to_first_choice():
    assert ar.key_for("OK", CHOICES) == "1"


def test_no_maps_to_no_labeled_choice():
    assert ar.key_for("やめて", CHOICES) == "3"  # "No, ..." の選択肢


def test_bare_digit_uses_that_choice_directly():
    assert ar.key_for("2", CHOICES) == "2"
    assert ar.key_for("3", CHOICES) == "3"


def test_invalid_digit_falls_through():
    # 選択肢に無い数字は承認語でないので None
    assert ar.key_for("9", CHOICES) is None


def test_normal_chat_returns_no_key():
    assert ar.key_for("予定教えて", CHOICES) is None


def test_punctuation_tolerated():
    assert ar.key_for("OK！", CHOICES) == "1"
    assert ar.key_for("いいよ〜", CHOICES) == "1"
