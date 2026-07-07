"""diary_state: 下書き状態機械。ファイル永続化でサーバ再起動でも消えない。"""
from interactive import diary_state as st


def test_start_and_accumulate(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "_active.json")
    assert st.is_active() is False
    st.start("2026-07-07", now="t0")
    assert st.is_active() and st.phase() == "collecting" and st.date() == "2026-07-07"
    st.append_text("箇条書き1", now="t1")
    st.append_text("箇条書き2", now="t2")
    assert st.raw() == "箇条書き1\n箇条書き2"
    assert st.last() == "t2"


def test_photos_and_captions(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "_active.json")
    st.start("2026-07-07", now="t0")
    st.append_photo("1.jpg", "秩父鉄道の電車", now="t1")
    assert st.photos() == [{"file": "1.jpg", "caption": "秩父鉄道の電車"}]
    assert st.captions() == ["秩父鉄道の電車"]


def test_confirming_and_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "_active.json")
    st.start("2026-07-07", now="t0")
    st.set_confirming({"title": "x", "tags": [], "body": "b"}, now="t1")
    assert st.phase() == "confirming"
    assert st.composed()["body"] == "b"
    st.clear()
    assert st.is_active() is False


def test_state_persists_across_reload(tmp_path, monkeypatch):
    f = tmp_path / "_active.json"
    monkeypatch.setattr(st, "STATE_FILE", f)
    st.start("2026-07-07", now="t0")
    st.append_text("消えないで", now="t1")
    # 別プロセス相当: ファイルから読み直す(モジュール内キャッシュを使わない)
    assert st.is_active() and st.raw() == "消えないで"


def test_reopen_keeps_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "_active.json")
    st.start("2026-07-07", now="t0")
    st.append_text("下書き", now="t1")
    st.set_confirming({"title": "x", "tags": [], "body": "b"}, now="t2")
    st.reopen(now="t3")
    assert st.phase() == "collecting"
    assert st.raw() == "下書き"          # 下書きは残る
    assert st.composed() is None
