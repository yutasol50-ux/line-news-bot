from interactive import approval_parse as ap

PROMPT = """\
● Bash(echo hi)
  ⎿  Running…

Do you want to proceed?
❯ 1. Yes
  2. Yes, and don't ask again for echo commands
  3. No, and tell Claude what to do differently (esc)
"""

IDLE = """\
✻ Churned for 59s
───────────────
❯
  ? for shortcuts
"""


def test_is_prompt_true_on_permission_prompt():
    assert ap.is_prompt(PROMPT) is True


def test_is_prompt_false_on_idle():
    assert ap.is_prompt(IDLE) is False


def test_parse_extracts_question_and_choices():
    r = ap.parse(PROMPT)
    assert r["question"] == "Do you want to proceed?"
    keys = [c["key"] for c in r["choices"]]
    assert keys == ["1", "2", "3"]
    assert r["choices"][0]["label"].startswith("Yes")
    assert "ask again" in r["choices"][1]["label"]


def test_parse_returns_none_on_idle():
    assert ap.parse(IDLE) is None
