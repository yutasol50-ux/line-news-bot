#!/usr/bin/env python3
"""LINEのテキストをHermes api_server(ローカル)へ渡し、応答文字列を返す薄い配線。

失敗しても例外を出さず安全な定型文を返す(LINEが無反応にならないように)。
"""
import os
import requests

_SAFE = "ごめん、いま調子が悪いみたい。もう一回送ってくれる?"


def ask(text: str, session_id: str = "line-owner") -> str:
    url = os.environ.get("HERMES_API_URL", "http://localhost:8642/v1/chat/completions")
    key = os.environ.get("HERMES_API_KEY", "")
    headers = {"Content-Type": "application/json", "X-Hermes-Session-Id": session_id}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = {"model": "hermes-agent", "messages": [{"role": "user", "content": text}]}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=180)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        return (content or "").strip() or "(からっぽの返事だったよ)"
    except Exception as e:
        print(f"[ERROR] hermes_brain: {e}")
        return _SAFE
