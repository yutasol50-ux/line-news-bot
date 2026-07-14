import os, interactive.voice_drain as vd, interactive.voice_intake as vi

def test_drain_reprocesses_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(vi, "PENDING_DIR", str(tmp_path))
    open(os.path.join(str(tmp_path), "1.m4a"), "wb").write(b"x")
    open(os.path.join(str(tmp_path), "2.m4a"), "wb").write(b"x")
    done = []
    n = vd.drain(process=lambda mid: done.append(mid))
    assert n == 2 and set(done) == {"1", "2"}
