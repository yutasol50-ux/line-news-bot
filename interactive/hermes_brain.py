#!/usr/bin/env python3
"""LINEのテキストをHermes api_server(ローカル)へ渡し、応答文字列を返す薄い配線。

失敗しても例外を出さず安全な定型文を返す(LINEが無反応にならないように)。
"""
import os
import requests
from datetime import datetime, timezone, timedelta

_SAFE = "ごめん、いま調子が悪いみたい。もう一回送ってくれる?"
_JST = timezone(timedelta(hours=9))
_WD = ("月", "火", "水", "木", "金", "土", "日")  # Mon..Sun

# LINE専属アシスタントとしての振る舞い指示(coreプロンプトの上に重ねるephemeral)。
# 目的: Haikuが最新情報や事実を「記憶+URL捏造」で答える事故を防ぎ、必ずツールで裏を取らせる。
_SYSTEM_PROMPT = (
    "あなたはLINE上でオーナー(Yuta)専属のアシスタントです。\n"
    "【ツール利用の鉄則】\n"
    "- 最新情報・時事・価格や数値データ・実在するURL・「調べて」「比較して」系の依頼には、"
    "記憶や推測で答えず、必ず web ツールで裏を取ってから答える。\n"
    "- 重い調査(比較・長文レポート)は delegate_task で資料屋(web専用)に任せる。"
    "その際 goal には必ず『調査結果を"
    "最終回答としてMarkdown本文で返すこと。ファイル作成・コード実行・保存はせず、web調査のみ行うこと』と明記する。\n"
    "- 確信の持てない事実は捏造しない。URLや数字をでっち上げない。ツールで確認できなければ、その旨を正直に伝える。\n"
    "- 逆に、雑談や既知の一般常識・自分の意見で足りる場合はツールを使わず簡潔に答えてよい。"
)


def _now_prefix() -> str:
    """モデルに"今日"を明示する1行。Haikuが日付を推測して過去に予定を書く事故を防ぐ。"""
    now = datetime.now(_JST)
    return f"[現在日時: {now:%Y-%m-%d}（{_WD[now.weekday()]}）{now:%H:%M} JST]\n"


def ask(text: str, session_id: str = "line-owner", timeout: int = 180) -> str:
    url = os.environ.get("HERMES_API_URL", "http://localhost:8642/v1/chat/completions")
    key = os.environ.get("HERMES_API_KEY", "")
    headers = {"Content-Type": "application/json", "X-Hermes-Session-Id": session_id}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    content = _now_prefix() + text
    payload = {
        "model": "hermes-agent",
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        return (content or "").strip() or "(からっぽの返事だったよ)"
    except Exception as e:
        print(f"[ERROR] hermes_brain: {e}")
        return _SAFE
