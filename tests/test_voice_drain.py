import os, interactive.voice_drain as vd, interactive.voice_intake as vi

def test_drain_reprocesses_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(vi, "PENDING_DIR", str(tmp_path))
    open(os.path.join(str(tmp_path), "1.m4a"), "wb").write(b"x")
    open(os.path.join(str(tmp_path), "2.m4a"), "wb").write(b"x")
    done = []
    n = vd.drain(process=lambda mid: done.append(mid))
    assert n == 2 and set(done) == {"1", "2"}

def test_drain_ignores_failed_dir(tmp_path, monkeypatch):
    """failed/(恒久失敗として隔離済み)はdrainの再処理対象に含めない(Finding 4)。"""
    pending = tmp_path / "pending"
    failed = tmp_path / "failed"
    os.makedirs(pending); os.makedirs(failed)
    monkeypatch.setattr(vi, "PENDING_DIR", str(pending))
    monkeypatch.setattr(vi, "FAILED_DIR", str(failed))
    open(os.path.join(str(pending), "1.m4a"), "wb").write(b"x")
    open(os.path.join(str(failed), "2.m4a"), "wb").write(b"x")

    done = []
    n = vd.drain(process=lambda mid: done.append(mid))
    assert n == 1
    assert done == ["1"]

def test_drain_ignores_dotfiles(tmp_path, monkeypatch):
    """.gitkeep等のドットファイルは音声ではないので再処理対象にしない。"""
    monkeypatch.setattr(vi, "PENDING_DIR", str(tmp_path))
    open(os.path.join(str(tmp_path), ".gitkeep"), "wb").write(b"")
    open(os.path.join(str(tmp_path), "1.m4a"), "wb").write(b"x")
    done = []
    n = vd.drain(process=lambda mid: done.append(mid))
    assert n == 1 and done == ["1"]  # .gitkeep は無視、空mid("")も生成されない
