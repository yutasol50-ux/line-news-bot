#!/usr/bin/env python3
"""NHK総合RSSのトップ記事1件を返す。スコアリング・分類なし。"""
import re
import requests
import xml.etree.ElementTree as ET

NHK_TOP = "https://www3.nhk.or.jp/rss/news/cat0.xml"


def get_news_block() -> str | None:
    try:
        resp = requests.get(
            NHK_TOP, timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SecretaryBot/1.0)"},
        )
        resp.raise_for_status()
        raw = resp.content
        raw = re.sub(rb'xmlns(?::\w+)?="[^"]*"', b'', raw)
        raw = re.sub(rb"xmlns(?::\w+)?='[^']*'", b'', raw)
        raw = re.sub(rb'<(/?)[\w][\w.-]*:([\w][\w.-]*)', rb'<\1\2', raw)
        root = ET.fromstring(raw)

        item = root.find(".//item")
        if item is None:
            return None
        title_el = item.find("title")
        link_el = item.find("link")
        title = (title_el.text or "").strip() if title_el is not None else ""
        link = (link_el.text or "").strip() if link_el is not None else ""
        if not title:
            return None
        block = f"📰 今朝の一報\n・{title}（NHK）"
        if link:
            block += f"\n{link}"
        return block
    except Exception as e:
        print(f"[WARN] ニュース取得失敗: {e}")
        return None


if __name__ == "__main__":
    print(get_news_block() or "(ニュース取得失敗)")
