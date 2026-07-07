"""media_intake.handle(取得→読解→Hermesへ受け渡し)のテスト。全依存をinjectする。"""
import interactive.media_intake as mi


def _mk(**over):
    calls = {"routed": [], "replied": []}

    def fetch(mid): return over.get("fetch_ret", (b"bytes", "image/jpeg"))
    def read(data, mtype): return over.get("read_ret", "領収書 3200円 5/1")
    def route(text, rt, sid): calls["routed"].append((text, rt, sid))
    def reply(rt, text): calls["replied"].append((rt, text))

    if over.get("fetch_raises"):
        def fetch(mid): raise RuntimeError("net down")  # noqa: E306,E704

    return calls, dict(fetch=fetch, read=read, route=route, reply=reply)


def test_image_extraction_is_routed_to_hermes_as_text():
    calls, dep = _mk()
    r = mi.handle("MID", "image", "RT", **dep)
    assert r == "handled"
    assert calls["replied"] == []                 # 直接replyせずHermes経由
    assert len(calls["routed"]) == 1
    text, rt, sid = calls["routed"][0]
    assert rt == "RT" and sid == "line-owner"
    assert "領収書 3200円 5/1" in text             # 読み取り結果が本文に入る
    assert "画像" in text                          # 画像由来と分かる前置き


def test_pdf_file_is_supported():
    calls, dep = _mk(fetch_ret=(b"%PDF", "application/pdf"), read_ret="請求書 合計 12,000円")
    r = mi.handle("MID", "file", "RT", **dep)
    assert r == "handled"
    text, _, _ = calls["routed"][0]
    assert "請求書 合計 12,000円" in text


def test_unsupported_file_type_replies_politely():
    calls, dep = _mk(fetch_ret=(b"xlsxdata", "application/vnd.ms-excel"))
    r = mi.handle("MID", "file", "RT", **dep)
    assert r == "unsupported"
    assert calls["routed"] == []                   # Hermesへ渡さない
    assert len(calls["replied"]) == 1
    assert "読め" in calls["replied"][0][1]         # 「まだ読めない」旨


def test_empty_extraction_replies_failure():
    calls, dep = _mk(read_ret="")
    r = mi.handle("MID", "image", "RT", **dep)
    assert r == "read_error"
    assert calls["routed"] == []
    assert len(calls["replied"]) == 1


def test_fetch_failure_replies_failure():
    calls, dep = _mk(fetch_raises=True)
    r = mi.handle("MID", "image", "RT", **dep)
    assert r == "fetch_error"
    assert calls["routed"] == []
    assert len(calls["replied"]) == 1
