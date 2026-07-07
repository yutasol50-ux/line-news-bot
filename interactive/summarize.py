#!/usr/bin/env python3
"""資料屋レポートをHaikuで本物の3点要約にする層。

LINEトークに載せる「要点」を、先頭を刈るだけの疑似要約(deliver_report._summarize)
から Haiku による実要約へ格上げする。API失敗時は安全に先頭刈りへフォールバックし、
配達(LINE push)を絶対に止めない。飛ばすのは文字だけなので安く済む。
"""
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# ANTHROPIC_API_KEY は hermes 側の .env に置いてある(資料屋 deliver_report と同じ鍵束)。
load_dotenv(Path.home() / ".hermes" / ".env")

_MODEL = "claude-haiku-4-5"
_ENDPOINT = "https://api.anthropic.com/v1/messages"
_MAX_INPUT = 12000  # レポート本文をHaikuへ渡す上限(長文の暴発を防ぐ・要点抽出には十分)
_PROMPT = (
    "次のレポートを、LINEで一目で掴める日本語の要点3つにまとめて。\n"
    "・「・」で始まる箇条書き3行だけを書く。前置き・締めの挨拶は書かない。\n"
    "・固有名詞や数字など核心は残す。冗長な説明は削る。\n\n"
    "--- レポート ---\n{body}"
)


def _fallback(text: str, max_chars: int) -> str:
    """要約LLMを使わない先頭刈り(deliver_report._summarize と同じ挙動)。"""
    head = text.strip()
    return head if len(head) <= max_chars else head[:max_chars].rstrip() + " …"


def summarize(text: str, max_chars: int = 400, timeout: int = 30) -> str:
    """レポートをHaikuで3点要約。失敗時は先頭刈りへフォールバック(絶対に例外を出さない)。"""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    body = text.strip()
    if not key or not body:
        return _fallback(text, max_chars)
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
                "max_tokens": 512,
                "messages": [
                    {"role": "user", "content": _PROMPT.format(body=body[:_MAX_INPUT])}
                ],
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        out = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        ).strip()
        return out or _fallback(text, max_chars)
    except Exception as e:  # ネット/認証/レート等 — 配達を止めない
        print(f"[ERROR] summarize: {e}")
        return _fallback(text, max_chars)
