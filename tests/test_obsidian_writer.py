import interactive.obsidian_writer as ow

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
