"""research_delivery.deliver: Gmail送信を差し替えて 保存・要点・成否を検証。"""
from interactive import research_delivery as rd


def test_deliver_saves_summarizes_and_reports_success(monkeypatch, tmp_path):
    sent = {}
    md = tmp_path / "2026-07-06-t.md"

    class _FakeDR:
        @staticmethod
        def _save_markdown(report, title):
            md.write_text(report, encoding="utf-8")
            return md

        @staticmethod
        def _send_email_with_attachment(title, body, md_path):
            sent["title"] = title
            sent["md"] = md_path

    monkeypatch.setitem(__import__("sys").modules, "deliver_report", _FakeDR)

    summary, md_path, ok = rd.deliver(
        "テスト", "レポート本文" * 100, summarize=lambda t, m: t[:m]
    )

    assert ok is True
    assert sent["title"] == "テスト"
    assert md.read_text(encoding="utf-8").startswith("レポート本文")
    assert summary.startswith("レポート本文")
    assert md_path == str(md)


def test_deliver_uses_injected_summarizer(monkeypatch, tmp_path):
    """要点は先頭刈りでなく、注入した要約器(=本番はHaiku)の出力を使う。"""
    md = tmp_path / "s.md"

    class _FakeDR:
        @staticmethod
        def _save_markdown(report, title):
            md.write_text(report, encoding="utf-8")
            return md

        @staticmethod
        def _send_email_with_attachment(title, body, md_path):
            pass

    monkeypatch.setitem(__import__("sys").modules, "deliver_report", _FakeDR)

    summary, md_path, ok = rd.deliver(
        "題", "本文" * 100, summarize=lambda t, m: "・要点1\n・要点2\n・要点3"
    )

    assert ok is True
    assert summary == "・要点1\n・要点2\n・要点3"  # 先頭刈りではない
    assert md.read_text(encoding="utf-8").startswith("本文")


def test_deliver_marks_email_fail_but_keeps_file(monkeypatch, tmp_path):
    md = tmp_path / "x.md"

    class _FakeDR:
        @staticmethod
        def _save_markdown(report, title):
            md.write_text(report, encoding="utf-8")
            return md

        @staticmethod
        def _send_email_with_attachment(title, body, md_path):
            raise RuntimeError("SMTP down")

    monkeypatch.setitem(__import__("sys").modules, "deliver_report", _FakeDR)

    summary, md_path, ok = rd.deliver("題", "本文", summarize=lambda t, m: t[:m])

    assert ok is False           # メールは失敗
    assert md.exists()           # でも全文は保存済み(欠落なし)
    assert md_path == str(md)
