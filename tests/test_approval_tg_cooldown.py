import importlib


def _server(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_TOKEN", "sekret")
    monkeypatch.setenv("APPROVAL_STORE", str(tmp_path / "p.json"))
    from interactive import server
    importlib.reload(server)
    return server


def test_cooldown_allows_first_blocks_within_window(tmp_path, monkeypatch):
    s = _server(tmp_path, monkeypatch)
    # 基準時刻を注入して決定的に
    assert s._tg_cooldown_ok(300, now=1000.0) is True    # 初回OK
    assert s._tg_cooldown_ok(300, now=1100.0) is False   # 100秒後=まだ中→ブロック
    assert s._tg_cooldown_ok(300, now=1250.0) is False   # 250秒後=まだ中
    assert s._tg_cooldown_ok(300, now=1301.0) is True    # 301秒後=クールダウン明け→OK


def test_cooldown_zero_always_allows(tmp_path, monkeypatch):
    s = _server(tmp_path, monkeypatch)
    assert s._tg_cooldown_ok(0, now=5.0) is True
    assert s._tg_cooldown_ok(0, now=5.0) is True
