#!/usr/bin/env python3
"""資料屋レポートの配達層。

Markdownレポートを .md 保存 → Gmail に自分宛添付送信し、LINE用の要点を返す。
中核の SMTP/保存は hermes-cowork の deliver_report を再利用する(実績あり・Gmail鍵は ~/.hermes/.env)。
"""
import sys
from pathlib import Path

# hermes-cowork の deliver_report を import できるようにする(コア無改造で再利用)。
_COWORK = Path.home() / "project" / "hermes-cowork"
if str(_COWORK) not in sys.path:
    sys.path.insert(0, str(_COWORK))


def deliver(title: str, report_markdown: str, max_summary: int = 400, summarize=None):
    """レポートを保存し Gmail 添付送信する。

    戻り値: (summary, md_path, email_ok)
      - summary : LINE 要点用(Haikuによる本物の3点要約。失敗時は先頭刈りへ自動退避)
      - md_path : 保存した .md の絶対パス(str)
      - email_ok: Gmail 送信に成功したか
    保存は必ず先に行うので、メール失敗時も全文は md_path に残る(欠落させない)。
    summarize は (text, max_chars)->str の要約器。省略時は Haiku 要約を使う(テストで差し替え可)。
    """
    import deliver_report as _dr  # 遅延importでテスト時の副作用を避ける

    if summarize is None:
        from interactive.summarize import summarize as summarize

    md_path = _dr._save_markdown(report_markdown, title)
    summary = summarize(report_markdown, max_summary)
    email_ok = True
    try:
        body = f"{title}\n\n{summary}\n\n（全文は添付の .md を参照）"
        _dr._send_email_with_attachment(title, body, md_path)
    except Exception as e:  # SMTP/認証失敗など
        print(f"[ERROR] research_delivery: Gmail送信失敗: {e}")
        email_ok = False
    return summary, str(md_path), email_ok
