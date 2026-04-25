#!/usr/bin/env python3
"""
パーソナライズニュース自動配信システム（LINE + Cohere版）

使用方法:
  python3 news_delivery.py fetch          # ニュース取得・要約（深夜3時）
  python3 news_delivery.py send economy   # 経済ニュース送信
  python3 news_delivery.py send work      # 仕事・自己啓発送信
  python3 news_delivery.py send english   # 英語学習送信
  python3 news_delivery.py test           # テスト送信
  python3 news_delivery.py status         # API使用状況確認
  python3 news_delivery.py reset          # カウンターリセット
"""
import json
import os
import sys
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
import cohere

# .envを読み込む
load_dotenv(Path(__file__).parent / ".env")

import request_counter

# ====== 設定 ======
COHERE_API_KEY = os.environ["COHERE_API_KEY"]
LINE_ACCESS_TOKEN = os.environ["LINE_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

co = cohere.ClientV2(api_key=COHERE_API_KEY)

JST = timezone(timedelta(hours=9))
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_FILE = DATA_DIR / "news_cache.json"

# ====== RSSソース定義 ======
RSS_SOURCES = {
    "economy": [
        {"name": "Yahoo JP経済",  "url": "https://news.yahoo.co.jp/rss/topics/business.xml"},
        {"name": "NHK経済",       "url": "https://www3.nhk.or.jp/rss/news/cat4.xml"},
        {"name": "東洋経済",      "url": "https://toyokeizai.net/list/feed/rss"},
        {"name": "WSJ Markets",   "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"},
        {"name": "BBC World",     "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    ],
    "work": [
        {"name": "東洋経済",       "url": "https://toyokeizai.net/list/feed/rss"},
        {"name": "Lifehacker JP",  "url": "https://www.lifehacker.jp/feed/index.xml"},
        {"name": "O'Reilly Radar", "url": "https://feeds.feedburner.com/oreilly/radar/atom"},
        {"name": "VentureBeat",    "url": "https://feeds.feedburner.com/venturebeat/SZYF"},
    ],
    "english": [
        {"name": "VOA Learning English", "url": "https://learningenglish.voanews.com/podcast/"},
        {"name": "BBC World News",       "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    ],
}

# ====== プロンプトテンプレート ======
PROMPTS = {
    "economy": """以下のニュースについて、あなたが持つ知識も活用して解説してください。
タイトルのみの場合もそのトピックについて解説してください。

ニュース:
{content}

以下の形式で回答してください:
【要約】
（3行以内で簡潔に。タイトルのみの場合はそのトピックの背景・意味を説明）

【重要度】★X/5
【投資家ポイント】（市場や投資への影響を1行で）""",

    "work": """以下のニュースについて、あなたが持つ知識も活用して解説してください。
タイトルのみの場合もそのトピックについて解説してください。

ニュース:
{content}

以下の形式で回答してください:
【要約】
（3行以内で簡潔に。タイトルのみの場合はそのトピックの実務的意義を説明）

【重要度】★X/5
【実務ポイント】（すぐに使えるアクションや示唆を1行で）""",

    "english": """以下の英語ニュースを英語学習のために解説してください。
タイトルのみの場合もそのトピックについて英語学習コンテンツを作成してください。

ニュース:
{content}

以下の形式で出力してください:
【原文（B1レベル）】
（B1レベルの平易な英語で要約、2〜3文）

【日本語訳】
（自然な日本語訳）

【重要単語】
1. word - 意味
2. word - 意味
3. word - 意味""",
}

# ====== RSS取得 ======
def fetch_rss(url: str, timeout: int = 15) -> list[dict]:
    try:
        resp = requests.get(
            url, timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"},
            allow_redirects=True,
        )
        resp.raise_for_status()

        import re
        raw = resp.content
        raw = re.sub(rb'xmlns(?::\w+)?="[^"]*"', b'', raw)
        raw = re.sub(rb"xmlns(?::\w+)?='[^']*'", b'', raw)
        raw = re.sub(rb'<(/?)[\w][\w.-]*:([\w][\w.-]*)', rb'<\1\2', raw)
        raw = re.sub(rb' [\w][\w.-]*:([\w][\w.-]*)=', rb' \1=', raw)
        root = ET.fromstring(raw)

        items = root.findall(".//item")
        if not items:
            items = root.findall(".//entry")

        articles = []
        for item in items[:5]:
            def get_text(*tags):
                for tag in tags:
                    el = item.find(tag)
                    if el is not None:
                        text = el.text or el.get("href", "")
                        if text:
                            return text.strip()
                return ""

            title = get_text("title")
            desc = get_text("description", "summary", "content", "encoded")
            link = get_text("link", "url")
            pub = get_text("pubDate", "published", "updated", "date")

            if desc:
                desc = re.sub(r'<[^>]+>', '', desc)[:500]

            if title:
                articles.append({
                    "title": title,
                    "description": desc,
                    "link": link,
                    "pubDate": pub,
                })
        return articles
    except Exception as e:
        print(f"[WARN] RSS取得失敗 {url}: {e}")
        return []


# ====== Cohere API呼び出し ======
def call_cohere(prompt: str) -> str | None:
    if not request_counter.can_request(1):
        print("[ERROR] 1日のリクエスト上限に達しました")
        return None

    try:
        response = co.chat(
            model="command-r-plus-08-2024",
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.message.content[0].text
        status = request_counter.increment(1)

        if status["warning"]:
            send_line(f"⚠️ API残り {status['remaining']} 回")

        return text.strip()
    except Exception as e:
        print(f"[ERROR] Cohere API呼び出し失敗: {e}")
        return None


# ====== LINE送信 ======
def send_line(text: str) -> bool:
    chunks = [text[i:i+4900] for i in range(0, len(text), 4900)]
    success = True
    for chunk in chunks:
        try:
            resp = requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers={
                    "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "to": LINE_USER_ID,
                    "messages": [{"type": "text", "text": chunk}]
                },
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"[ERROR] LINE送信失敗: {resp.status_code} {resp.text[:200]}")
                success = False
            time.sleep(1)
        except Exception as e:
            print(f"[ERROR] LINE送信例外: {e}")
            success = False
    return success


# ====== キャッシュ管理 ======
def save_cache(data: dict) -> None:
    CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ====== ニュース取得・要約 ======
def cmd_fetch() -> None:
    print(f"[{datetime.now(JST).strftime('%H:%M:%S')}] ニュース取得・要約開始")
    cache = {}

    for category, sources in RSS_SOURCES.items():
        print(f"  カテゴリ: {category}")
        summaries = []

        for source in sources:
            print(f"    RSS取得: {source['name']}")
            articles = fetch_rss(source["url"])

            for art in articles[:3]:
                if not request_counter.can_request(1):
                    print("[WARN] リクエスト上限のため処理停止")
                    break

                content = f"タイトル: {art['title']}\n本文: {art['description']}"
                prompt = PROMPTS[category].format(content=content)
                print(f"      要約中: {art['title'][:50]}...")

                summary = call_cohere(prompt)
                if summary:
                    summaries.append({
                        "source": source["name"],
                        "title": art["title"],
                        "link": art["link"],
                        "pubDate": art["pubDate"],
                        "summary": summary,
                    })
                time.sleep(2)

        cache[category] = {
            "fetched_at": datetime.now(JST).isoformat(),
            "articles": summaries,
        }
        print(f"  {category}: {len(summaries)}件 要約完了")

    save_cache(cache)
    print(f"\n[完了] 取得・要約完了。{request_counter.status()}")


# ====== LINE送信コマンド ======
def cmd_send(category: str) -> None:
    label_map = {
        "economy": "経済・マーケット",
        "work":    "仕事・自己啓発",
        "english": "英語学習",
    }

    if category not in label_map:
        print(f"[ERROR] 不明なカテゴリ: {category}")
        sys.exit(1)

    label = label_map[category]
    cache = load_cache()

    if category not in cache or not cache[category]["articles"]:
        print(f"[ERROR] キャッシュなし。先に fetch を実行してください。")
        sys.exit(1)

    data = cache[category]
    fetched_at = data["fetched_at"][:16].replace("T", " ")
    articles = data["articles"]

    now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M")
    header = (
        f"📰 {label}ニュース | {now_str}\n"
        f"（取得: {fetched_at} JST | {len(articles)}件）\n"
        f"{'─' * 30}"
    )
    send_line(header)

    for i, art in enumerate(articles, 1):
        emoji = {"economy": "📈", "work": "💼", "english": "🇬🇧"}.get(category, "📄")
        msg = (
            f"{emoji} [{i}/{len(articles)}] {art['title'][:80]}\n"
            f"ソース: {art['source']}"
            + (f"\n{art['link']}" if art.get("link") else "")
            + f"\n\n{art['summary']}"
        )
        send_line(msg)
        time.sleep(1.5)

    print(f"[完了] {label}: {len(articles)}件送信完了")


# ====== テスト送信 ======
def cmd_test() -> None:
    now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M")
    msg = (
        f"🤖 [テスト] LINE News Bot 接続確認\n"
        f"時刻: {now_str} JST\n"
        f"ニュース自動配信システム起動確認メッセージです。\n"
        f"{request_counter.status()}"
    )
    ok = send_line(msg)
    print("✅ 成功" if ok else "❌ 失敗")


# ====== ステータス表示 ======
def cmd_status() -> None:
    print(request_counter.status())
    cache = load_cache()
    print("\n--- キャッシュ状況 ---")
    for cat, data in cache.items():
        n = len(data.get("articles", []))
        t = data.get("fetched_at", "なし")[:16]
        print(f"  {cat}: {n}件 (取得: {t})")


# ====== エントリーポイント ======
if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] == "status":
        cmd_status()
    elif args[0] == "fetch":
        cmd_fetch()
    elif args[0] == "send":
        if len(args) < 2:
            print("使用法: python3 news_delivery.py send [economy|work|english]")
            sys.exit(1)
        cmd_send(args[1])
    elif args[0] == "test":
        cmd_test()
    elif args[0] == "reset":
        request_counter.reset()
        print("カウンターをリセットしました")
    else:
        print(__doc__)
        sys.exit(1)
