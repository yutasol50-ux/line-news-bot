#!/usr/bin/env python3
"""LINEに来た画像/PDFを「テキスト」に変換してHermesへ渡すオーケストレータ。

流れ: LINE content取得(line_media) → Haiku読解(vision) → 前置きを付けて
既存の自己昇格ディスパッチャ(research_async.handle)へ。Hermesは読み取り済み
テキストだけを受け取り、整理してLINEへ返す(ファイルは一切触らせない)。
取得/読解に失敗したら、無反応にせず定型文をユーザーへ返す。
"""
from interactive import line_media
from interactive import research_async
from interactive.vision import read as vision_read
from interactive.vision import _IMAGE_TYPES  # 対応画像typeはvisionと単一の真実で共有(ドリフト防止)
from shared import line_client

_UNSUPPORTED = "ごめん、その形式のファイルはまだ読めないんだ。写真かPDFなら読めるよ！"
_READ_FAIL = "うまく読み取れなかった…もう一度送ってみてくれる?"
_FETCH_FAIL = "ファイルの取得でつまずいちゃった。もう一度送ってみて。"


def _normalize(content_type):
    """対応するmedia_typeを返す。非対応なら None。"""
    if content_type in _IMAGE_TYPES:
        return content_type
    if content_type == "application/pdf":
        return "application/pdf"
    return None


def _wrap(media_type, extraction):
    """読み取りテキストに、Hermesへの前置き指示を付ける。"""
    what = "PDF" if media_type == "application/pdf" else "画像"
    return (
        f"[オーナーが{what}を共有しました]\n"
        f"以下はその{what}から読み取った内容です"
        "（あなたに現物は見えていません。この読み取り結果だけで応答してください）:\n"
        "---\n"
        f"{extraction}\n"
        "---\n"
        "内容を日本語で簡潔に整理して伝えてください。日付・金額・締切・タスクなど"
        "後で役立つ情報があれば拾ってください。特に指示がなければ要点整理だけでよく、"
        "その場合はweb検索などのツールは使わないでください。"
    )


def handle(message_id, kind, reply_token, *, session_id="line-owner",
           fetch=line_media.fetch_content, read=vision_read,
           route=research_async.handle, reply=line_client.reply):
    """画像/PDFを取り込みHermes経由でLINEへ返す。戻り値=経路文字列。"""
    try:
        data, content_type = fetch(message_id)
    except Exception as e:
        print(f"[ERROR] media_intake fetch: {e}")
        reply(reply_token, _FETCH_FAIL)
        return "fetch_error"

    media_type = _normalize(content_type)
    if media_type is None:
        print(f"[INFO] media_intake unsupported: content_type={content_type}")
        reply(reply_token, _UNSUPPORTED)
        return "unsupported"

    extraction = read(data, media_type)
    if not extraction:
        print(f"[ERROR] media_intake read_error: media_type={media_type} bytes={len(data)}")
        reply(reply_token, _READ_FAIL)
        return "read_error"

    route(_wrap(media_type, extraction), reply_token, session_id)
    return "handled"
