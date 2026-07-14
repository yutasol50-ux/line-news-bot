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

def test_process_transcribe_failure_keeps_pending_and_pushes_busy(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    os.makedirs(vi.PENDING_DIR, exist_ok=True)
    fp = os.path.join(vi.PENDING_DIR, "100.m4a"); open(fp,"wb").write(b"x")
    pushed = []
    def boom(p): raise RuntimeError("gemini busy")
    r = vi.process("100",
        transcribe=boom,
        draft=lambda t: ("タイトル", "## 要点\n- x\n"),
        write=lambda **kw: "/vault/_inbox/2026-07-14-タイトル.md",
        push=lambda t: pushed.append(t),
        today="2026-07-14")
    assert r == "retry_later"
    assert os.path.exists(fp)       # 失敗時はpendingを残す=あとでdrainが再開
    assert pushed and pushed[0] == vi._BUSY

def test_process_no_pending_file_returns_gone(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    # PENDING_DIRすら存在しない状態
    r = vi.process("nope",
        transcribe=lambda p: "x",
        draft=lambda t: ("t", "b"),
        write=lambda **kw: "/x.md",
        push=lambda t: None,
        today="2026-07-14")
    assert r == "gone"

def test_handle_fetch_failure_does_not_leave_claim_and_allows_retry(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    replies = []
    def failing_fetch(mid): raise RuntimeError("network down")
    r = vi.handle("200", "RT",
                  fetch=failing_fetch,
                  reply=lambda rt, t: replies.append((rt, t)),
                  spawn=lambda fn: None)
    assert r == "fetch_error"
    assert not os.path.exists(vi.PENDING_DIR) or not os.listdir(vi.PENDING_DIR)
    assert replies  # エラー返信が送られた

    # 未クレームのまま=再送で同じidが処理できる(重複扱いされない)
    spawned = []
    r2 = vi.handle("200", "RT",
                   fetch=lambda mid: (b"audiobytes", "audio/m4a"),
                   reply=lambda rt, t: replies.append((rt, t)),
                   spawn=lambda fn: spawned.append(fn))
    assert r2 == "accepted"
    assert spawned

def test_handle_claim_is_atomic_second_call_is_duplicate(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert vi.claim("300") is True
    assert vi.claim("300") is False

    spawned = []
    r1 = vi.handle("300", "RT",
                   fetch=lambda mid: (b"a", "audio/m4a"),
                   reply=lambda rt, t: None,
                   spawn=lambda fn: spawned.append(fn))
    # "300"は既にclaim済みなのでhandleはduplicate扱い
    assert r1 == "duplicate"
    assert not spawned

    r2 = vi.handle("301", "RT",
                   fetch=lambda mid: (b"a", "audio/m4a"),
                   reply=lambda rt, t: None,
                   spawn=lambda fn: spawned.append(fn))
    r3 = vi.handle("301", "RT",
                   fetch=lambda mid: (b"a", "audio/m4a"),
                   reply=lambda rt, t: None,
                   spawn=lambda fn: spawned.append(fn))
    assert r2 == "accepted"
    assert r3 == "duplicate"
    assert len(spawned) == 1  # 同一idの並行/連続handleでspawnは1回だけ
