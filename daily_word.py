#!/usr/bin/env python3
"""Cohereで「本日の一語」を生成。四字熟語・故事成語・哲学/思想用語・難読語などミックス。
既出語は data/seen_words.json に蓄積して重複回避。"""
import json
import os
import re
from pathlib import Path
from dotenv import load_dotenv
import cohere

load_dotenv(Path(__file__).parent / ".env")

COHERE_API_KEY = os.environ["COHERE_API_KEY"]
co = cohere.ClientV2(api_key=COHERE_API_KEY)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
SEEN_FILE = DATA_DIR / "seen_words.json"

PROMPT = """あなたは教養豊かな秘書です。日本人が知っておくと一段賢くなる「今日の一語」を1つ選んでください。

ジャンルはミックスでお願いします（四字熟語・故事成語・哲学/思想用語・難読語・概念語など、毎回バラけさせる）。
中学〜大人の教養レベル。あまりに平易な語（例：努力、友情）は避ける。

次の語は過去に出したので避けてください: {seen}

以下の形式で **厳密に** 出力してください（前置き・後置きは一切不要）:
語：（漢字。読み仮名があれば「漢字（よみ）」）
意味：（1〜2行で簡潔に）
由来：（由来や成り立ち、または一言の深掘り。1〜2行）"""


def _load_seen() -> list[str]:
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_seen(words: list[str]) -> None:
    SEEN_FILE.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")


def get_word_block() -> str | None:
    """整形済みの「本日の一語」ブロックを返す。失敗時はNone。"""
    seen = _load_seen()
    seen_str = "、".join(seen[-60:]) if seen else "（なし）"
    try:
        resp = co.chat(
            model="command-r-plus-08-2024",
            messages=[{"role": "user", "content": PROMPT.format(seen=seen_str)}],
        )
        text = resp.message.content[0].text.strip()
    except Exception as e:
        print(f"[WARN] 一語生成失敗: {e}")
        return None

    m = re.search(r'語：\s*(.+)', text)
    word = m.group(1).strip() if m else None
    if word:
        # 重複登録防止
        key = re.sub(r'（.*?）', '', word).strip()
        if key and key not in seen:
            seen.append(key)
            _save_seen(seen)

    return f"📖 本日の一語\n{text}"


if __name__ == "__main__":
    print(get_word_block() or "(一語生成失敗)")
