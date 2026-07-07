#!/usr/bin/env python3
"""画像/PDFをHaiku(vision/document)で日本語テキストに読み取る層。

Hermesはファイルを扱えない/扱わせない方針なので、メディアはここで「テキスト」に
変換してから渡す。summarize.py と同じAnthropicのMessages API直叩き・同じ鍵束。
出力は「忠実な読み取り」に徹し、整理・判断は後段(Hermes)に任せる。
失敗しても例外を出さず "" を返す(呼び出し側が定型文でフォロー)。
"""
import base64
import os
from io import BytesIO
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path.home() / ".hermes" / ".env")

_MODEL = "claude-haiku-4-5"
_ENDPOINT = "https://api.anthropic.com/v1/messages"
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_MAX_EDGE = 1568  # Anthropic推奨の最長辺

_PROMPT = (
    "この画像/PDFに写っている情報を、日本語で忠実に読み取ってください。\n"
    "・本文テキストは省略せず書き出す（金額・日付・番号・固有名詞を正確に）。\n"
    "・表や図、写真の要素は簡潔に描写する。\n"
    "・要約や意見・前置きは加えず、読み取れた情報だけを出力する。"
)


def _prepare_image(data, media_type):
    """画像を最長辺1568pxへ縮小しJPEG化(ベストエフォート)。失敗時は原本を返す。"""
    try:
        from PIL import Image
        im = Image.open(BytesIO(data)).convert("RGB")
        im.thumbnail((_MAX_EDGE, _MAX_EDGE))
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:
        print(f"[WARN] vision downscale skipped: {e}")
        return data, media_type


def read(data, media_type, *, timeout=60):
    """画像/PDFをHaikuで読み取り日本語テキストで返す。失敗時は ""(例外を出さない)。"""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or not data:
        return ""

    if media_type == "application/pdf":
        block = {"type": "document", "source": {
            "type": "base64", "media_type": "application/pdf",
            "data": base64.b64encode(data).decode(),
        }}
    elif media_type in _IMAGE_TYPES:
        data, media_type = _prepare_image(data, media_type)
        block = {"type": "image", "source": {
            "type": "base64", "media_type": media_type,
            "data": base64.b64encode(data).decode(),
        }}
    else:
        return ""  # 非対応(docx/xlsx/audio等)

    try:
        r = requests.post(
            _ENDPOINT,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _MODEL,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": [block, {"type": "text", "text": _PROMPT}]}],
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data_json = r.json()
        out = "".join(
            b.get("text", "") for b in data_json.get("content", []) if b.get("type") == "text"
        ).strip()
        return out
    except Exception as e:
        print(f"[ERROR] vision.read: {e}")
        return ""
