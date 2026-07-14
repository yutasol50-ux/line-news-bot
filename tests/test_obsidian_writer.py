import interactive.obsidian_writer as ow
import os

def test_write_draft_creates_md_with_frontmatter(tmp_path):
    p = ow.write_draft(
        title="散歩メモ AIとお金",
        body="## 要点\n- a\n- b\n",
        transcript="生の文字起こし全文",
        message_id="12345",
        inbox=str(tmp_path),
        today="2026-07-14",
    )
    assert p.endswith(".md")
    text = (tmp_path / __import__("os").path.basename(p)).read_text()
    assert "status: draft" in text
    assert "message_id: 12345" in text
    assert "散歩メモ AIとお金" in text
    assert "## 全文（Gemini文字起こし）" in text
    assert "生の文字起こし全文" in text

def test_write_draft_returns_absolute_path(tmp_path, monkeypatch):
    """write_draft must return an absolute path even with relative inbox."""
    # 相対inboxを検証しつつ、書き込み先はtmp_path配下に閉じ込める(リポジトリを汚さない)
    monkeypatch.chdir(tmp_path)
    relative_inbox = "relative_dir"
    p = ow.write_draft(
        title="テスト",
        body="本文",
        transcript="文字起こし",
        message_id="abc",
        inbox=relative_inbox,
        today="2026-07-14",
    )
    assert os.path.isabs(p), f"Path should be absolute, got: {p}"
    assert os.path.exists(p), f"File should exist at absolute path: {p}"

def test_write_draft_collision_suffix(tmp_path):
    """Successive calls with same title/today increment with -2.md, -3.md, etc."""
    inbox = str(tmp_path)
    p1 = ow.write_draft(
        title="同じタイトル",
        body="初回",
        transcript="文字起こし1",
        message_id="msg1",
        inbox=inbox,
        today="2026-07-14",
    )
    p2 = ow.write_draft(
        title="同じタイトル",
        body="二回目",
        transcript="文字起こし2",
        message_id="msg2",
        inbox=inbox,
        today="2026-07-14",
    )
    assert p1 != p2
    assert os.path.exists(p1)
    assert os.path.exists(p2)
    assert p2.endswith("-2.md"), f"Second file should end with -2.md, got: {p2}"

def test_write_draft_slug_sanitization(tmp_path):
    """Unsafe filesystem chars in title are stripped from filename."""
    inbox = str(tmp_path)
    p = ow.write_draft(
        title="AI/お金: メモ",
        body="テスト",
        transcript="文字起こし",
        message_id="xyz",
        inbox=inbox,
        today="2026-07-14",
    )
    basename = os.path.basename(p)
    unsafe_chars = r'\/:*?"<>|'
    for char in unsafe_chars:
        assert char not in basename, f"Unsafe char '{char}' found in filename: {basename}"
    assert os.path.exists(p)

def test_write_draft_empty_title_fallback(tmp_path):
    """Empty title falls back to 'voicememo' in filename."""
    inbox = str(tmp_path)
    p = ow.write_draft(
        title="",
        body="内容",
        transcript="文字起こし",
        message_id="empty",
        inbox=inbox,
        today="2026-07-14",
    )
    basename = os.path.basename(p)
    assert "voicememo" in basename, f"Empty title should fallback to voicememo, got: {basename}"
    assert os.path.exists(p)
