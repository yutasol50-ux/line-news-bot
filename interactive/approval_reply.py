"""LINEテキスト返信を Claude Code 承認の Yes/No に解釈する純関数。

Apple Watch はボタン(postback)を出せないので、「OK」等のテキスト返信で承認できるようにする。
承認待ちがある時だけ server.py がこれを使う(通常時はHermesへHermes雑談へ流す)。
"""

# 末尾の飾りだけ落とす(ーは オーケー 等で意味を持つので残す)
_TRIM = "！!。.、,~〜 　"

_YES = {
    "ok", "okです", "おk", "おけ", "おけー", "おっけ", "おっけー", "オッケー", "オーケー",
    "はい", "いいよ", "いいですよ", "いいね", "進めて", "すすめて", "承認", "どうぞ",
    "ゴー", "go", "yes", "y", "うん", "オーケー", "了解進めて",
}
_NO = {
    "no", "n", "いいえ", "だめ", "ダメ", "やめて", "やめ", "やめとく", "却下", "中止",
    "ストップ", "stop", "ちがう", "違う", "だめだ",
}


def _norm(text: str) -> str:
    return (text or "").strip().strip(_TRIM).lower()


def classify(text: str):
    """Yes/No/None を返す。承認語でなければ None(=通常の会話)。"""
    t = _norm(text)
    if t in _YES:
        return "yes"
    if t in _NO:
        return "no"
    return None


def key_for(text: str, choices: list):
    """承認テキスト→注入する選択肢key。該当しなければ None。

    - 数字そのもの("2"等)が選択肢keyにあればそれを直接使う(番号指定)
    - "OK"等=yes → 先頭選択肢(Claude Codeでは 1=Yes)
    - "やめて"等=no → ラベルが No/いいえ で始まる選択肢、無ければ最後
    """
    t = _norm(text)
    keys = [c.get("key") for c in choices]
    if t.isdigit():
        return t if t in keys else None
    verdict = classify(text)
    if verdict == "yes":
        return choices[0]["key"] if choices else None
    if verdict == "no":
        for c in choices:
            lab = (c.get("label") or "").lower()
            if lab.startswith("no") or lab.startswith("いいえ"):
                return c["key"]
        return choices[-1]["key"] if choices else None
    return None
