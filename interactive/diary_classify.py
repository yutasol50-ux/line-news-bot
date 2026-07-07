#!/usr/bin/env python3
"""日記モード中の返信を affirm/reject/more/content に分類する。

「これでいい?」への肯定なら何でも確定スイッチにする(キーワード一致でなく意味で判定)。
API失敗時は簡易キーワード、それも外れれば content(=中身として貯め、取りこぼさない)。
"""
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path.home() / ".hermes" / ".env")

_MODEL = "claude-haiku-4-5"
_ENDPOINT = "https://api.anthropic.com/v1/messages"
_LABELS = ("affirm", "reject", "more", "content")
_PROMPT = (
    "日記アプリで「これでいい?」と聞いた直後のユーザー返信を分類します。\n"
    "次の1語だけを出力(説明禁止):\n"
    "affirm = 肯定・OK・書き終わり(いいよ/ok/おけ/おk/終わり/とりあえず 等)\n"
    "reject = 否定・やり直したい(ちがう/直して 等)\n"
    "more = まだ書き足したいが新しい内容は無い(まだ/ちょっと待って 等)\n"
    "content = 新しい日記の中身(出来事・気持ちなど)\n\n"
    "返信: {text}"
)

_AFFIRM_WORDS = ("いいよ", "いい", "ok", "ｏｋ", "おけ", "おk", "終わり", "おわり",
                 "とりあえず", "だいじょうぶ", "大丈夫", "うん", "はい")
_REJECT_WORDS = ("ちがう", "違う", "直し", "やり直", "だめ", "ダメ")
_MORE_WORDS = ("まだ", "ちょっと待", "待って")


def _keyword(text: str) -> str:
    t = text.strip().lower()
    if len(t) <= 12:  # 短い返事だけ制御語とみなす(長文は中身)
        if any(w in t for w in _REJECT_WORDS):
            return "reject"
        if any(w in t for w in _MORE_WORDS):
            return "more"
        if any(w in t for w in _AFFIRM_WORDS):
            return "affirm"
    return "content"


def classify(text: str, *, timeout: int = 15) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    body = (text or "").strip()
    if not body:
        return "more"
    if not key:
        return _keyword(body)
    try:
        r = requests.post(
            _ENDPOINT,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": _MODEL, "max_tokens": 8,
                  "messages": [{"role": "user",
                                "content": _PROMPT.format(text=body[:2000])}]},
            timeout=timeout,
        )
        r.raise_for_status()
        out = "".join(b.get("text", "") for b in r.json().get("content", [])
                      if b.get("type") == "text").strip().lower()
        for label in _LABELS:
            if label in out:
                return label
        return _keyword(body)
    except Exception as e:
        print(f"[ERROR] diary_classify: {e}")
        return _keyword(body)
