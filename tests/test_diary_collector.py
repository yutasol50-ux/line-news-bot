"""diary_collector: 状態別の会話ハンドリング。全依存をinjectして実API/LINEを叩かない。"""
from interactive import diary_collector as col
from interactive import diary_state as st


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "_active.json")
    replies = []
    dep = dict(reply=lambda rt, text: replies.append(text))
    return replies, dep


def test_content_is_appended_and_asks_confirm(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-07", now="t0")
    r = col.handle_text("駅でバタバタした", "RT", now="t1",
                        classify=lambda t: "content", **dep)
    assert r == "appended"
    assert st.raw() == "駅でバタバタした"
    assert "これでいい" in replies[-1]


def test_affirm_composes_and_shows_confirm(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-07", now="t0")
    st.append_text("・当務\n・つかれた", now="t1")
    r = col.handle_text("いいよ", "RT", now="t2",
                        classify=lambda t: "affirm",
                        compose=lambda raw, caps, date: {"title": "当務", "tags": ["疲れ"],
                                                         "body": "今日は当務だった。"},
                        **dep)
    assert r == "confirm_shown"
    assert st.phase() == "confirming"
    assert "今日は当務だった。" in replies[-1] and "これでいい" in replies[-1]


def test_confirm_affirm_saves(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-07", now="t0")
    st.append_text("原文", now="t1")
    st.set_confirming({"title": "当務", "tags": ["疲れ"], "body": "本文"}, now="t2")
    saved = {}
    r = col.handle_text("おけ", "RT", now="t3",
                        classify=lambda t: "affirm",
                        store=type("S", (), {"save": staticmethod(lambda e: saved.update(e) or "path")}),
                        **dep)
    assert r == "saved"
    assert saved["body"] == "本文" and saved["raw"] == "原文" and saved["date"] == "2026-07-07"
    assert st.is_active() is False
    assert "保存した" in replies[-1]


def test_more_nudges_without_appending(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-07", now="t0")
    r = col.handle_text("まだ！", "RT", now="t1", classify=lambda t: "more", **dep)
    assert r == "nudge"
    assert st.raw() == ""          # 追記されない


def test_photo_is_captioned_and_stored(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-07", now="t0")
    fake_store = type("S", (), {"save_photo": staticmethod(lambda d, data: "1.jpg")})
    r = col.handle_photo("MID", "RT", now="t1",
                         fetch=lambda mid: (b"JPG", "image/jpeg"),
                         read=lambda data, mtype: "秩父鉄道の電車",
                         store=fake_store, **dep)
    assert r == "photo_added"
    assert st.photos() == [{"file": "1.jpg", "caption": "秩父鉄道の電車"}]


def test_finalize_timeout_saves_stale_draft(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-06", now="2026-07-06T21:00:00+09:00")
    st.append_text("寝落ち分", now="2026-07-06T21:05:00+09:00")
    saved = {}
    done = col.finalize_timeout(
        now_iso="2026-07-07T02:30:00+09:00",
        compose=lambda raw, caps, date: {"title": "t", "tags": [], "body": "清書"},
        store=type("S", (), {"save": staticmethod(lambda e: saved.update(e) or "p")}))
    assert done is True
    assert saved["date"] == "2026-07-06" and saved["raw"] == "寝落ち分"
    assert st.is_active() is False


def test_finalize_timeout_respects_grace_before_cutoff(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-06", now="2026-07-06T23:50:00+09:00")
    st.append_text("日付またぎ中", now="2026-07-07T00:05:00+09:00")
    saved = {}
    done = col.finalize_timeout(
        now_iso="2026-07-07T00:10:00+09:00",
        compose=lambda raw, caps, date: {"title": "t", "tags": [], "body": "清書"},
        store=type("S", (), {"save": staticmethod(lambda e: saved.update(e) or "p")}))
    assert done is False
    assert saved == {}
    assert st.is_active() is True


def test_confirm_reject_reopens_without_saving(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-07", now="t0")
    st.append_text("原文", now="t1")
    st.set_confirming({"title": "当務", "tags": [], "body": "本文"}, now="t2")

    def _no_save(e):
        raise AssertionError("store.save should not be called on reject")

    r = col.handle_text("ちがう", "RT", now="t3",
                        classify=lambda t: "reject",
                        store=type("S", (), {"save": staticmethod(_no_save)}),
                        **dep)
    assert r == "reopened"
    assert st.phase() == "collecting"
    assert st.is_active() is True


def test_photo_fetch_failure_still_replies(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    st.start("2026-07-07", now="t0")

    def _fail(mid):
        raise RuntimeError("net")

    r = col.handle_photo("MID", "RT", now="t1", fetch=_fail, **dep)
    assert r == "photo_fail"
    assert len(replies) > 0


def test_start_manual_starts_and_greets(tmp_path, monkeypatch):
    replies, dep = _setup(tmp_path, monkeypatch)
    r = col.start_manual("RT", now="2026-07-07T21:00:00+09:00", **dep)
    assert r == "started"
    assert st.is_active() is True
    assert "日記モード" in replies[-1]
