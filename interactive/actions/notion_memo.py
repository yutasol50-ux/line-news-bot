#!/usr/bin/env python3
"""Notion APIでメモDBに行(ページ)を追記する。"""
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_MEMO_DB_ID = os.environ.get("NOTION_MEMO_DB_ID", "")
_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def add(content: str, tags: list[str] | None = None, when_iso: str | None = None) -> str:
    """メモDBに1行追加。DBは『名前(title)/日付(date)/タグ(multi_select)』を想定。"""
    props = {
        "名前": {"title": [{"text": {"content": content[:1900]}}]},
    }
    if when_iso:
        props["日付"] = {"date": {"start": when_iso}}
    if tags:
        props["タグ"] = {"multi_select": [{"name": t} for t in tags]}

    resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers=_HEADERS,
        json={"parent": {"database_id": NOTION_MEMO_DB_ID}, "properties": props},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Notion追記失敗: {resp.status_code} {resp.text[:300]}")
    return resp.json().get("url", "")
