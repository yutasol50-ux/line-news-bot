#!/usr/bin/env python3
"""日記の本棚Webページ。テーブルの窮屈さの逆=広いカードでゆったり見せる。

依存は diary_store のみ。HTMLは自己完結(外部CSS/JSなし)。
"""
import html as _html
from flask import Blueprint, abort, send_file

from interactive import diary_store

bp = Blueprint("diary", __name__)

_PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>📔 日記</title>
<style>
:root{{color-scheme:light dark}}
body{{font-family:-apple-system,"Hiragino Sans",sans-serif;margin:0;
background:#faf8f4;color:#2b2b2b;line-height:1.9}}
@media(prefers-color-scheme:dark){{body{{background:#1a1a1a;color:#e8e6e2}}}}
header{{padding:28px 20px 8px;font-size:26px;font-weight:700}}
.wrap{{max-width:720px;margin:0 auto;padding:12px 16px 60px}}
.card{{background:#fff;border-radius:16px;padding:22px 24px;margin:18px 0;
box-shadow:0 2px 14px rgba(0,0,0,.06)}}
@media(prefers-color-scheme:dark){{.card{{background:#262626;box-shadow:none}}}}
.date{{font-size:13px;opacity:.6}}
.title{{font-size:20px;font-weight:700;margin:2px 0 10px}}
.tags{{margin:0 0 12px}}
.tag{{display:inline-block;background:#efe9dd;border-radius:999px;
padding:3px 12px;font-size:12px;margin-right:6px}}
@media(prefers-color-scheme:dark){{.tag{{background:#3a3a3a}}}}
.body{{white-space:pre-wrap;font-size:16px}}
.photos{{margin-top:14px;display:flex;flex-wrap:wrap;gap:10px}}
.photos img{{width:100%;max-width:220px;border-radius:12px}}
.empty{{opacity:.6;text-align:center;padding:60px 0}}
</style></head><body>
<header>📔 日記</header><div class="wrap">{cards}</div></body></html>"""


def _card(e: dict) -> str:
    date = _html.escape(e.get("date", ""))
    title = _html.escape(e.get("title", ""))
    body = _html.escape(e.get("body", ""))
    tags = "".join(f'<span class="tag">{_html.escape(str(t))}</span>'
                   for t in e.get("tags", []))
    imgs = "".join(
        f'<img src="/diary/media/{date}/{_html.escape(p.get("file", ""))}" '
        f'alt="{_html.escape(p.get("caption", ""))}" loading="lazy">'
        for p in e.get("photos", []))
    photos = f'<div class="photos">{imgs}</div>' if imgs else ""
    return (f'<div class="card"><div class="date">{date}</div>'
            f'<div class="title">{title}</div>'
            f'<div class="tags">{tags}</div>'
            f'<div class="body">{body}</div>{photos}</div>')


@bp.get("/diary")
def diary_index():
    entries = diary_store.list_entries()
    if not entries:
        cards = '<div class="empty">まだ日記はないよ。夜に書こう📔</div>'
    else:
        cards = "".join(_card(e) for e in entries)
    return _PAGE.format(cards=cards)


@bp.get("/diary/media/<date>/<path:filename>")
def diary_media(date, filename):
    base = (diary_store.DIARY_DIR / "media").resolve()
    p = diary_store.media_path(date, filename).resolve()
    # containment: p must be strictly under base (blocks ../ traversal & symlinks)
    if base not in p.parents:
        abort(404)
    if not p.is_file():
        abort(404)
    return send_file(str(p))
