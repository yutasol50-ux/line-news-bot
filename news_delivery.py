#!/usr/bin/env python3
"""
パーソナライズニュース自動配信システム（LINE + Cohere版）

使用方法:
  python3 news_delivery.py fetch    # ニュース取得・要約（深夜3時）
  python3 news_delivery.py send     # ニュース送信（朝7時）
  python3 news_delivery.py test     # テスト送信
  python3 news_delivery.py status   # スコア・API使用状況確認
  python3 news_delivery.py reset    # カウンターリセット
"""
import json
import os
import re
import sys
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
import cohere

load_dotenv(Path(__file__).parent / ".env")
import request_counter

COHERE_API_KEY = os.environ["COHERE_API_KEY"]
LINE_ACCESS_TOKEN = os.environ["LINE_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

co = cohere.ClientV2(api_key=COHERE_API_KEY)

JST = timezone(timedelta(hours=9))
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_FILE = DATA_DIR / "news_cache.json"
SCORES_FILE = Path(__file__).parent / "scores.json"

ALL_LABELS = [
    "AI", "テクノロジー", "セキュリティ", "宇宙・科学",
    "経済", "株式・投資", "仮想通貨", "不動産",
    "仕事", "起業・スタートアップ", "教育", "英語",
    "政治・国際", "社会・日本", "環境・エネルギー",
    "健康・医療", "ライフスタイル", "エンタメ", "スポーツ", "その他",
]

RSS_SOURCES = [
    {"name": "Yahoo JP経済",        "url": "https://news.yahoo.co.jp/rss/topics/business.xml"},
    {"name": "NHK総合",             "url": "https://www3.nhk.or.jp/rss/news/cat0.xml"},
    {"name": "NHK経済",             "url": "https://www3.nhk.or.jp/rss/news/cat4.xml"},
    {"name": "東洋経済",            "url": "https://toyokeizai.net/list/feed/rss"},
    {"name": "WSJ Markets",         "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"},
    {"name": "BBC World",           "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "Lifehacker JP",       "url": "https://www.lifehacker.jp/feed/index.xml"},
    {"name": "O'Reilly Radar",      "url": "https://feeds.feedburner.com/oreilly/radar/atom"},
    {"name": "VentureBeat",         "url": "https://feeds.feedburner.com/venturebeat/SZYF"},
    {"name": "VOA Learning English", "url": "https://learningenglish.voanews.com/podcast/"},
]

SUMMARY_PROMPT = """以下のニュース記事を分析してください。

タイトル: {title}
本文: {desc}

以下の形式で回答してください：
【要点】
（2行以内で簡潔に。タイトルのみの場合は背景を説明）

【ラベル】
（次のラベルから最も適切な1つだけ選択: {labels}）"""


# ====== スコア管理 ======

def load_scores() -> dict:
    if SCORES_FILE.exists():
        try:
            return json.loads(SCORES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "labels": {l: 5.0 for l in ALL_LABELS},
        "settings": {
            "decay": 0.93, "like_delta": 1.0, "dislike_delta": 1.0,
            "max_articles": 6, "trending_count": 2,
        },
        "last_decay": "",
    }


def save_scores(scores: dict) -> None:
    SCORES_FILE.write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_decay(scores: dict) -> None:
    today = datetime.now(JST).strftime("%Y-%m-%d")
    if scores.get("last_decay") == today:
        return
    decay = scores["settings"]["decay"]
    for label in scores["labels"]:
        current = scores["labels"][label]
        scores["labels"][label] = round(5.0 + (current - 5.0) * decay, 2)
    scores["last_decay"] = today
    save_scores(scores)
    print(f"[減衰適用] ×{decay} → 5.0に近づける")


# ====== RSS取得 ======

def get_field(item, *tags) -> str:
    for tag in tags:
        el = item.find(tag)
        if el is not None:
            text = el.text or el.get("href", "")
            if text:
                return text.strip()
    return ""


def fetch_rss(url: str, timeout: int = 15) -> list[dict]:
    try:
        resp = requests.get(
            url, timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"},
            allow_redirects=True,
        )
        resp.raise_for_status()

        raw = resp.content
        raw = re.sub(rb'xmlns(?::\w+)?="[^"]*"', b'', raw)
        raw = re.sub(rb"xmlns(?::\w+)?='[^']*'", b'', raw)
        raw = re.sub(rb'<(/?)[\w][\w.-]*:([\w][\w.-]*)', rb'<\1\2', raw)
        raw = re.sub(rb' [\w][\w.-]*:([\w][\w.-]*)=', rb' \1=', raw)
        root = ET.fromstring(raw)

        items = root.findall(".//item") or root.findall(".//entry")
        articles = []
        for item in items[:5]:
            title = get_field(item, "title")
            desc  = get_field(item, "description", "summary", "content", "encoded")
            link  = get_field(item, "link", "url")
            pub   = get_field(item, "pubDate", "published", "updated", "date")
            if desc:
                desc = re.sub(r'<[^>]+>', '', desc)[:400]
            if title:
                articles.append({"title": title, "description": desc, "link": link, "pubDate": pub})
        return articles
    except Exception as e:
        print(f"[WARN] RSS取得失敗 {url}: {e}")
        return []


# ====== トレンド検出 ======

def compute_trend_multipliers(articles: list[dict]) -> list[dict]:
    stop = {'の', 'に', 'は', 'が', 'を', 'で', 'と', 'も', 'や', 'な', 'て', 'た', 'し', 'から', 'まで', 'より'}

    def keywords(title: str) -> set:
        words = re.findall(r'[一-龯ぁ-んァ-ン]{2,}|[a-zA-Z]{3,}', title)
        return {w for w in words if w not in stop}

    kws = [keywords(a["title"]) for a in articles]
    for i, art in enumerate(articles):
        if not kws[i]:
            art["trend_multiplier"] = 1.0
            continue
        overlap = sum(1 for j, kw in enumerate(kws) if i != j and len(kws[i] & kw) >= 2)
        art["trend_multiplier"] = (1.5 if overlap >= 3 else 1.3 if overlap >= 2 else 1.1 if overlap >= 1 else 1.0)
    return articles


# ====== Cohere API ======

def call_cohere(prompt: str) -> str | None:
    if not request_counter.can_request(1):
        print("[ERROR] 1日のリクエスト上限に達しました")
        return None
    try:
        response = co.chat(
            model="command-r-plus-08-2024",
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.message.content[0].text
        status = request_counter.increment(1)
        if status["warning"]:
            send_line(f"⚠️ API残り {status['remaining']} 回")
        return text.strip()
    except Exception as e:
        print(f"[ERROR] Cohere API失敗: {e}")
        return None


def parse_label(text: str) -> str:
    m = re.search(r'【ラベル】\s*\n?\s*(.+)', text)
    if m:
        candidate = m.group(1).strip().split()[0]
        if candidate in ALL_LABELS:
            return candidate
    for label in ALL_LABELS:
        if label in text:
            return label
    return "その他"


def parse_summary(text: str) -> str:
    m = re.search(r'【要点】\s*\n([\s\S]+?)(?:\n【|$)', text)
    if m:
        return m.group(1).strip()
    return text[:80]


# ====== LINE送信 ======

def send_line(text: str) -> bool:
    chunks = [text[i:i+4900] for i in range(0, len(text), 4900)]
    success = True
    for chunk in chunks:
        try:
            resp = requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers={"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"},
                json={"to": LINE_USER_ID, "messages": [{"type": "text", "text": chunk}]},
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


def send_line_quick_reply(text: str, items: list[dict]) -> bool:
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"},
            json={
                "to": LINE_USER_ID,
                "messages": [{"type": "text", "text": text, "quickReply": {"items": items}}],
            },
            timeout=30,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[ERROR] QuickReply送信例外: {e}")
        return False


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


# ====== コマンド: fetch ======

def cmd_fetch() -> None:
    print(f"[{datetime.now(JST).strftime('%H:%M:%S')}] ニュース取得・要約開始")
    all_articles: list[dict] = []

    for source in RSS_SOURCES:
        print(f"  RSS取得: {source['name']}")
        for art in fetch_rss(source["url"])[:3]:
            art["source"] = source["name"]
            all_articles.append(art)

    all_articles = compute_trend_multipliers(all_articles)

    # URL重複除去
    seen: set[str] = set()
    unique = [a for a in all_articles if a["link"] not in seen and not seen.add(a["link"])]  # type: ignore
    print(f"  重複除去後: {len(unique)}件")

    label_list = "、".join(ALL_LABELS)
    summaries = []
    for art in unique:
        if not request_counter.can_request(1):
            print("[WARN] リクエスト上限のため処理停止")
            break

        prompt = SUMMARY_PROMPT.format(
            title=art["title"],
            desc=art["description"][:300],
            labels=label_list,
        )
        print(f"    解析中: {art['title'][:45]}...")

        result = call_cohere(prompt)
        if result:
            summaries.append({
                "source": art["source"],
                "title": art["title"],
                "link": art["link"],
                "pubDate": art["pubDate"],
                "label": parse_label(result),
                "summary": parse_summary(result),
                "trend_multiplier": art.get("trend_multiplier", 1.0),
            })
        time.sleep(1.5)

    save_cache({"fetched_at": datetime.now(JST).isoformat(), "articles": summaries})
    print(f"\n[完了] {len(summaries)}件取得。{request_counter.status()}")


# ====== コマンド: send ======

def cmd_send() -> None:
    scores = load_scores()
    apply_decay(scores)

    cache = load_cache()
    if not cache or not cache.get("articles"):
        print("[ERROR] キャッシュなし。先に fetch を実行してください。")
        sys.exit(1)

    label_scores = scores["labels"]
    settings = scores["settings"]
    articles = cache["articles"]

    for art in articles:
        ls = label_scores.get(art["label"], 5.0)
        tm = art.get("trend_multiplier", 1.0)
        art["final_score"] = round(ls * tm, 2)

    tc = settings.get("trending_count", 2)
    mc = settings.get("max_articles", 6)

    trending = sorted(
        [a for a in articles if a.get("trend_multiplier", 1.0) >= 1.3],
        key=lambda x: x["final_score"], reverse=True,
    )
    regular = sorted(
        [a for a in articles if a.get("trend_multiplier", 1.0) < 1.3],
        key=lambda x: x["final_score"], reverse=True,
    )

    seen: set[str] = set()
    selected = []
    for art in trending[:tc] + regular:
        if len(selected) >= mc:
            break
        if art["link"] not in seen:
            seen.add(art["link"])
            selected.append(art)

    now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M")
    send_line(f"📰 ニュース配信 {now_str}（{len(selected)}件）")
    time.sleep(1)

    labels_sent = []
    for art in selected:
        is_trend = art.get("trend_multiplier", 1.0) >= 1.3
        prefix = "🔥 " if is_trend else ""
        label = art["label"]
        score_str = f"{art['final_score']:.1f}"
        labels_sent.append(label)

        title_short = art["title"][:38]
        line1 = f"{prefix}{label}▶{score_str}｜「{title_short}」"
        msg = f"{line1}\n{art['link']}" if art.get("link") else line1
        send_line(msg)
        time.sleep(1.5)

    # 👍/👎 クイックリプライ（最後の1通）
    unique_labels = list(dict.fromkeys(labels_sent))[:6]
    qr_items = []
    for label in unique_labels:
        qr_items.append({"type": "action", "action": {"type": "message", "label": f"👍{label}", "text": f"LIKE:{label}"}})
        qr_items.append({"type": "action", "action": {"type": "message", "label": f"👎{label}", "text": f"BAD:{label}"}})

    send_line_quick_reply("気になった記事のラベルを教えてください👇", qr_items)
    print(f"[完了] {len(selected)}件送信完了")


# ====== コマンド: test ======

def cmd_test() -> None:
    now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M")
    scores = load_scores()
    top5 = sorted(scores["labels"].items(), key=lambda x: -x[1])[:5]
    label_str = "\n".join([f"  {k}: {v}" for k, v in top5])
    msg = (
        f"🤖 [テスト] LINE News Bot 接続確認\n"
        f"時刻: {now_str} JST\n"
        f"スコアTOP5:\n{label_str}\n"
        f"{request_counter.status()}"
    )
    ok = send_line(msg)
    print("✅ 成功" if ok else "❌ 失敗")


# ====== コマンド: status ======

def cmd_status() -> None:
    scores = load_scores()
    print("=== ラベルスコア ===")
    for label, score in sorted(scores["labels"].items(), key=lambda x: -x[1]):
        filled = int(score)
        bar = "█" * filled + "░" * (10 - filled)
        print(f"  {label:<18} [{bar}] {score:.1f}")
    print(f"\n{request_counter.status()}")
    cache = load_cache()
    if cache:
        n = len(cache.get("articles", []))
        t = cache.get("fetched_at", "なし")[:16]
        print(f"\nキャッシュ: {n}件 (取得: {t})")


# ====== エントリーポイント ======

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] == "status":
        cmd_status()
    elif args[0] == "fetch":
        cmd_fetch()
    elif args[0] == "send":
        cmd_send()
    elif args[0] == "test":
        cmd_test()
    elif args[0] == "reset":
        request_counter.reset()
        print("カウンターをリセットしました")
    else:
        print(__doc__)
        sys.exit(1)
