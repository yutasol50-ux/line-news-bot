#!/usr/bin/env python3
"""Gemini(REST, function calling)で 自然文 → 構造化アクション に変換する。"""
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-2.5-flash-lite"
ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
)

_TOOLS = [{"function_declarations": [
    {
        "name": "add_calendar_event",
        "description": "ユーザーが予定・アポイント・締切などを記録したい時に呼ぶ。",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "予定の件名"},
                "start": {"type": "string", "description": "開始日時 ISO8601 (+09:00)。時刻不明なら日付の00:00"},
                "end": {"type": "string", "description": "終了日時 ISO8601。不明ならstart+1時間"},
                "all_day": {"type": "boolean", "description": "時刻指定が無い終日予定ならtrue"},
            },
            "required": ["title", "start", "all_day"],
        },
    },
    {
        "name": "add_memo",
        "description": "予定ではない覚え書き・買い物・アイデア・あとで調べる事をメモする時に呼ぶ。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "メモ本文"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "任意の分類タグ"},
            },
            "required": ["content"],
        },
    },
]}]


def _system_instruction(now_iso: str) -> dict:
    return {"parts": [{"text":
        "あなたは渡辺さんの秘書。ユーザーの日本語メッセージを読み、"
        "予定なら add_calendar_event、覚え書きなら add_memo を呼ぶ。"
        "雑談や判断不能な場合は関数を呼ばず、短く親しみやすい日本語で返す。"
        f"現在の日時(JST)は {now_iso}。相対表現(明日/今週末等)はこれを基準に絶対日時へ変換する。"
    }]}


def _call_gemini(payload: dict) -> dict:
    """Gemini generateContent を叩く境界。テストで差し替える。"""
    resp = requests.post(
        ENDPOINT,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def parse_intent(text: str, now_iso: str) -> dict:
    payload = {
        "system_instruction": _system_instruction(now_iso),
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "tools": _TOOLS,
    }
    data = _call_gemini(payload)
    parts = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    for part in parts:
        fc = part.get("functionCall")
        if fc:
            name = fc.get("name")
            args = fc.get("args", {}) or {}
            if name == "add_calendar_event":
                return {"action": "add_calendar_event", "params": {
                    "title": args.get("title", "(無題)"),
                    "start": args.get("start"),
                    "end": args.get("end"),
                    "all_day": bool(args.get("all_day", False)),
                }, "message": ""}
            if name == "add_memo":
                return {"action": "add_memo", "params": {
                    "content": args.get("content", ""),
                    "tags": args.get("tags", []) or [],
                }, "message": ""}
    # 関数呼び出しが無ければ none。テキストをそのまま返信に使う。
    text_reply = next((p.get("text") for p in parts if p.get("text")), "うん、了解!")
    return {"action": "none", "params": {}, "message": text_reply}
