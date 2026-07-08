"""tmux capture-pane のテキストから Claude Code 承認プロンプトを解析する純関数。"""
import re

# 「❯ 1. Yes」「  2. ...」形式の選択肢行。先頭の ❯ / 空白を許容。
_CHOICE_RE = re.compile(r"^\s*(?:❯\s*)?(\d+)\.\s+(.*\S)\s*$")
# 承認プロンプトの合図(いずれか)。Claude Code の TUI 文言に依存するため複数許容。
_PROMPT_MARKERS = ("Do you want to proceed?", "Do you want to make this edit")


def _lines(text: str) -> list[str]:
    return text.replace("\r", "").split("\n")


def is_prompt(capture_text: str) -> bool:
    """承認プロンプトが表示中か。マーカー文言 + 番号選択肢が2つ以上あれば真。"""
    has_marker = any(m in capture_text for m in _PROMPT_MARKERS)
    n_choices = sum(1 for ln in _lines(capture_text) if _CHOICE_RE.match(ln))
    return has_marker and n_choices >= 2


def parse(capture_text: str) -> dict | None:
    """`{"question", "choices":[{"key","label"}]}` or None。"""
    if not is_prompt(capture_text):
        return None
    question = ""
    for ln in _lines(capture_text):
        if any(mk in ln for mk in _PROMPT_MARKERS):
            question = ln.strip()
            break
    choices = []
    for ln in _lines(capture_text):
        mo = _CHOICE_RE.match(ln)
        if mo:
            # ラベル末尾の "(esc)" 等の装飾は落とす
            label = re.sub(r"\s*\(esc\)\s*$", "", mo.group(2)).strip()
            choices.append({"key": mo.group(1), "label": label})
    return {"question": question, "choices": choices}
