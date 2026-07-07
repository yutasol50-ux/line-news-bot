#!/usr/bin/env python3
"""diary_prompt: 20時の声かけ。古い下書きを確定してから今日の日記モードを開始。"""
import diary_prompt


def test_run_finalizes_then_starts_then_pushes(monkeypatch):
    events = []
    monkeypatch.setattr(diary_prompt, "finalize_timeout",
                        lambda **k: events.append("finalize") or False)
    monkeypatch.setattr(diary_prompt.diary_state, "start",
                        lambda date, now: events.append(("start", date)))
    monkeypatch.setattr(diary_prompt.line_client, "push",
                        lambda text: events.append(("push", text)) or True)
    diary_prompt.run(now_iso="2026-07-07T20:00:00+09:00")
    assert events[0] == "finalize"
    assert events[1] == ("start", "2026-07-07")
    assert events[2][0] == "push"
    assert "今日" in events[2][1]
