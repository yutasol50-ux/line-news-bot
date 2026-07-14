import os, json, interactive.voice_intake as vi

def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(vi, "PENDING_DIR", str(tmp_path / "pending"))
    monkeypatch.setattr(vi, "SEEN_PATH", str(tmp_path / "seen.json"))
    monkeypatch.setattr(vi, "FAILED_DIR", str(tmp_path / "failed"))
    monkeypatch.setattr(vi, "ATTEMPTS_PATH", str(tmp_path / "attempts.json"))

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

def test_handle_save_pending_failure_does_not_leave_claim_and_allows_retry(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    replies = []
    original_save_pending = vi.save_pending
    def boom_save_pending(message_id, data, content_type):
        raise OSError("disk full")
    monkeypatch.setattr(vi, "save_pending", boom_save_pending)

    r = vi.handle("400", "RT",
                  fetch=lambda mid: (b"audiobytes", "audio/m4a"),
                  reply=lambda rt, t: replies.append((rt, t)),
                  spawn=lambda fn: None)
    assert r == "fetch_error"
    assert replies  # エラー返信が送られた
    assert not os.path.exists(vi.PENDING_DIR) or not os.listdir(vi.PENDING_DIR)

    # 未クレームのまま=再送で同じidが処理できる(save_pending失敗でも二度と再送不能にならない)
    monkeypatch.setattr(vi, "save_pending", original_save_pending)
    spawned = []
    r2 = vi.handle("400", "RT",
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


# --- Finding 2/5: seen.json の原子的書き込み+上限件数 -----------------------

def test_save_seen_is_atomic_partial_write_does_not_corrupt(tmp_path, monkeypatch):
    """os.replace が失敗しても既存のseen.jsonは無傷(tmpファイルに書いてから差し替えるため)。"""
    _setup(tmp_path, monkeypatch)
    vi.mark_seen("orig")
    good_content = open(vi.SEEN_PATH).read()

    def boom_replace(src, dst):
        raise OSError("crash mid-write")
    monkeypatch.setattr(vi.os, "replace", boom_replace)

    import pytest
    with pytest.raises(OSError):
        vi.mark_seen("new")

    assert open(vi.SEEN_PATH).read() == good_content

def test_seen_bounded_and_evicts_oldest_on_overflow(tmp_path, monkeypatch):
    """直近 _MAX_SEEN(2000)件だけ保持し、超過分は最も古いものから捨てる。"""
    _setup(tmp_path, monkeypatch)
    preset = [f"id{i}" for i in range(vi._MAX_SEEN)]  # 2000件を直接仕込む(高速化)
    vi._save_seen_ids(preset)
    vi.mark_seen("idNEW")  # これで2001件目→上限超過

    ids = json.load(open(vi.SEEN_PATH))
    assert len(ids) == vi._MAX_SEEN
    assert "id0" not in ids       # 最古が追い出された
    assert "idNEW" in ids         # 最新は残る
    assert vi.is_seen("idNEW") is True
    assert vi.is_seen("id0") is False

def test_corrupted_seen_json_loads_as_empty_and_does_not_crash(tmp_path, monkeypatch):
    """壊れた/切り詰められたseen.jsonでもクラッシュせず空扱いになる(既存挙動の維持)。"""
    _setup(tmp_path, monkeypatch)
    os.makedirs(os.path.dirname(vi.SEEN_PATH), exist_ok=True)
    with open(vi.SEEN_PATH, "w") as f:
        f.write("{not valid json...")
    assert vi.is_seen("anything") is False
    assert vi.claim("100") is True  # 壊れたファイルからでも新規claimできる


# --- Finding 4: 試行回数の上限+failed/への隔離 -------------------------------

def test_process_quarantines_after_max_attempts(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    os.makedirs(vi.PENDING_DIR, exist_ok=True)
    fp = os.path.join(vi.PENDING_DIR, "100.m4a"); open(fp, "wb").write(b"x")
    pushed = []
    def boom(p): raise RuntimeError("gemini busy")

    for _ in range(vi.MAX_ATTEMPTS - 1):
        r = vi.process("100", transcribe=boom,
                        draft=lambda t: ("タイトル", "本文"),
                        write=lambda **kw: "/x.md",
                        push=lambda t: pushed.append(t), today="2026-07-14")
        assert r == "retry_later"
        assert os.path.exists(fp)  # 上限未満はpendingに残る

    r = vi.process("100", transcribe=boom,
                    draft=lambda t: ("タイトル", "本文"),
                    write=lambda **kw: "/x.md",
                    push=lambda t: pushed.append(t), today="2026-07-14")
    assert r == "failed"
    assert not os.path.exists(fp)                                   # pendingから消えた
    assert os.path.exists(os.path.join(vi.FAILED_DIR, "100.m4a"))    # failed/へ隔離された
    assert pushed.count(vi._BUSY) == vi.MAX_ATTEMPTS - 1
    assert pushed.count(vi._FAILED) == 1                             # 最終通知は1回だけ

def test_process_below_attempt_cap_stays_pending_and_pushes_busy(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    os.makedirs(vi.PENDING_DIR, exist_ok=True)
    fp = os.path.join(vi.PENDING_DIR, "200.m4a"); open(fp, "wb").write(b"x")
    pushed = []
    def boom(p): raise RuntimeError("gemini busy")

    for _ in range(vi.MAX_ATTEMPTS - 1):
        r = vi.process("200", transcribe=boom,
                        draft=lambda t: ("タイトル", "本文"),
                        write=lambda **kw: "/x.md",
                        push=lambda t: pushed.append(t), today="2026-07-14")
        assert r == "retry_later"

    assert os.path.exists(fp)  # まだfailed/へは移されていない
    assert not os.path.isdir(vi.FAILED_DIR) or not os.listdir(vi.FAILED_DIR)
    assert pushed == [vi._BUSY] * (vi.MAX_ATTEMPTS - 1)

def test_process_success_after_prior_failures_clears_attempt_count(tmp_path, monkeypatch):
    """失敗を重ねた後に成功したら、試行カウントは片付く(次回また0から数える)。"""
    _setup(tmp_path, monkeypatch)
    os.makedirs(vi.PENDING_DIR, exist_ok=True)
    fp = os.path.join(vi.PENDING_DIR, "300.m4a"); open(fp, "wb").write(b"x")
    pushed = []
    vi.process("300", transcribe=lambda p: (_ for _ in ()).throw(RuntimeError("boom")),
               draft=lambda t: ("t", "b"), write=lambda **kw: "/x.md",
               push=lambda t: pushed.append(t), today="2026-07-14")
    assert vi._load_attempts().get("300") == 1

    r = vi.process("300", transcribe=lambda p: "全文",
                    draft=lambda t: ("タイトル", "## 要点\n- x\n"),
                    write=lambda **kw: "/vault/_inbox/x.md",
                    push=lambda t: pushed.append(t), today="2026-07-14")
    assert r == "handled"
    assert "300" not in vi._load_attempts()


# --- Minor: _quarantine の FileNotFoundError耐性 ------------------------------

def test_quarantine_tolerates_already_missing_source(tmp_path, monkeypatch):
    """並行drain/processでpendingが既に消えていても_quarantineは例外を出さない(冪等)。"""
    _setup(tmp_path, monkeypatch)
    missing = os.path.join(vi.PENDING_DIR, "gone.m4a")  # 存在しないファイル
    dest = vi._quarantine(missing)  # 例外を投げないこと
    assert dest == os.path.join(vi.FAILED_DIR, "gone.m4a")
    assert not os.path.exists(dest)  # 元々無かったので移動先にも実体はできない

def test_process_quarantine_survives_concurrent_removal_and_clears_attempts(tmp_path, monkeypatch):
    """quarantine実行の瞬間にpendingファイルが(並行drain等で)消えていても、
    process()の例外処理が完走し、attempts.jsonのエントリはちゃんと片付く。
    os.replaceそのものを差し替えて「_find_pendingが見つけた直後に他プロセスが消した」
    レースを再現する(_find_pending自体はfpがまだ存在する時点で見つける)。"""
    _setup(tmp_path, monkeypatch)
    os.makedirs(vi.PENDING_DIR, exist_ok=True)
    fp = os.path.join(vi.PENDING_DIR, "500.m4a"); open(fp, "wb").write(b"x")
    # MAX_ATTEMPTS-1 回まで失敗させて閾値の一歩手前にしておく
    def boom(p): raise RuntimeError("gemini busy")
    for _ in range(vi.MAX_ATTEMPTS - 1):
        vi.process("500", transcribe=boom, draft=lambda t: ("t", "b"),
                   write=lambda **kw: "/x.md", push=lambda t: None, today="2026-07-14")
    assert vi._load_attempts().get("500") == vi.MAX_ATTEMPTS - 1

    # _atomic_write_json(attempts.json/seen.json)も内部でos.replaceを使うため、
    # quarantine対象(fp→FAILED_DIR)の移動だけを狙い撃ちしてレースを再現する。
    original_replace = vi.os.replace
    def racy_replace(src, dst):
        if src == fp:
            os.remove(src)
            raise FileNotFoundError(src)
        return original_replace(src, dst)
    monkeypatch.setattr(vi.os, "replace", racy_replace)

    pushed = []
    r = vi.process("500", transcribe=boom, draft=lambda t: ("t", "b"),
                   write=lambda **kw: "/x.md", push=lambda t: pushed.append(t),
                   today="2026-07-14")
    assert r == "failed"
    assert "500" not in vi._load_attempts()  # 消えていてもattemptsは片付く
    assert pushed.count(vi._FAILED) == 1

    monkeypatch.setattr(vi.os, "replace", original_replace)
