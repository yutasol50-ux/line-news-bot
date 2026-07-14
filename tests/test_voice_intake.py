import os, interactive.voice_intake as vi

def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(vi, "PENDING_DIR", str(tmp_path / "pending"))
    monkeypatch.setattr(vi, "SEEN_PATH", str(tmp_path / "seen.json"))

def test_handle_saves_pending_and_replies(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    replies, spawned = [], []
    def fake_fetch(mid): return (b"audiobytes", "audio/m4a")
    vi.handle("100", "RT",
              fetch=fake_fetch,
              reply=lambda rt, t: replies.append((rt, t)),
              spawn=lambda fn: spawned.append(fn))
    assert os.path.exists(os.path.join(vi.PENDING_DIR, "100.m4a"))
    assert replies and replies[0][0] == "RT"
    assert spawned  # 裏処理が積まれた

def test_handle_dedup_skips_seen(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    vi.mark_seen("100")
    spawned = []
    r = vi.handle("100", "RT", fetch=lambda m: (b"x","audio/m4a"),
                  reply=lambda rt,t: None, spawn=lambda fn: spawned.append(fn))
    assert r == "duplicate"
    assert not spawned

def test_process_transcribes_and_writes(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    os.makedirs(vi.PENDING_DIR, exist_ok=True)
    fp = os.path.join(vi.PENDING_DIR, "100.m4a"); open(fp,"wb").write(b"x")
    pushed = []
    r = vi.process("100",
        transcribe=lambda p: "全文テキスト",
        draft=lambda t: ("タイトル", "## 要点\n- x\n"),
        write=lambda **kw: "/vault/_inbox/2026-07-14-タイトル.md",
        push=lambda t: pushed.append(t),
        today="2026-07-14")
    assert r == "handled"
    assert not os.path.exists(fp)   # 完了でpending削除
    assert pushed and "タイトル" in pushed[0]
