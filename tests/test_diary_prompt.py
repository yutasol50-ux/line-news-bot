#!/usr/bin/env python3
"""diary_prompt: 20時の声かけ。書きかけを保存してから今日の日記モードを開始。"""
import diary_prompt
from interactive import diary_state as st
from interactive import diary_store


def test_run_flushes_then_starts_then_pushes(monkeypatch):
    events = []
    monkeypatch.setattr(diary_prompt, "flush",
                        lambda **k: events.append("flush") or False)
    monkeypatch.setattr(diary_prompt.diary_state, "start",
                        lambda date, now: events.append(("start", date)))
    monkeypatch.setattr(diary_prompt.line_client, "push",
                        lambda text: events.append(("push", text)) or True)
    diary_prompt.run(now_iso="2026-07-07T20:00:00+09:00")
    assert events[0] == "flush"
    assert events[1] == ("start", "2026-07-07")
    assert events[2][0] == "push"
    assert "今日" in events[2][1]


def test_run_saves_same_day_in_progress_draft(tmp_path, monkeypatch):
    """同日の進行中下書きに中身があれば、新規開始前に必ず保存される(消失防止)。"""
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "_active.json")
    st.start("2026-07-07", now="2026-07-07T19:00:00+09:00")
    st.append_text("昼の書きかけ", now="2026-07-07T19:05:00+09:00")
    saved = []
    monkeypatch.setattr(diary_store, "save", lambda e: saved.append(e) or "p")
    monkeypatch.setattr(diary_prompt.line_client, "push", lambda text: True)
    diary_prompt.run(now_iso="2026-07-07T20:00:00+09:00")
    assert len(saved) == 1
    assert saved[0]["raw"] == "昼の書きかけ"
    assert saved[0]["date"] == "2026-07-07"
    # 保存後に今日の新規モードが開始されている
    assert st.is_active() is True


def test_reap_invokes_finalize_timeout(monkeypatch):
    called = []
    monkeypatch.setattr(diary_prompt, "finalize_timeout",
                        lambda **k: called.append(k) or True)
    diary_prompt.reap(now_iso="2026-07-08T02:00:00+09:00")
    assert len(called) == 1
    assert called[0]["now_iso"] == "2026-07-08T02:00:00+09:00"
