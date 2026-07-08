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

PROMPT_EDIT = """\
● Update(auth.py)

Do you want to make this edit to auth.py?
❯ 1. Yes
  2. Yes, allow all edits during this session
  3. No, and tell Claude what to do differently (esc)
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


def test_parse_keeps_full_question_line_for_edit_prompt():
    r = ap.parse(PROMPT_EDIT)
    assert r["question"] == "Do you want to make this edit to auth.py?"
    assert [c["key"] for c in r["choices"]] == ["1", "2", "3"]
