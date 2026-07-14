"""
Gemini 音声文字起こしコア（LINE音声→Obsidianノート機能の基礎モジュール）

`~/tool/gemini_transcribe.py` の CLI 版を、テスト可能な関数群として移植したもの。
- `transcribe`: 単一音声ファイルを文字起こし（inline / File API 自動切替、503/429リトライ+モデルフォールバック）
- `transcribe_long`: ffmpegで分割してから各チャンクを`transcribe`し連結（長尺音声向け）
- `draft_note`: 文字起こしからObsidianノートの下書き（タイトル+本文）を生成

すべての外部I/O（HTTP・subprocess・sleep）は引数で差し替え可能。
import時に副作用は起こさない（GEMINI_API_KEY未設定でもimportは成功する）。
"""
import os
import sys
import time
import json
import base64
import mimetypes
import subprocess
from pathlib import Path

import requests

API = "https://generativelanguage.googleapis.com"
MODEL = os.environ.get("TRANSCRIBE_MODEL", "gemini-2.5-flash")
FALLBACK_MODEL = "gemini-2.5-flash-lite"
INLINE_THRESHOLD = 7 * 1024 * 1024  # 7MB未満はinline、以上はFile API

TRANSCRIBE_PROMPT = (
    "この音声を日本語で文字起こししてください。"
    "話者が変わったら改行してください（分かる範囲で構いません）。"
    "相槌や言い淀みは適度に整えて、聞き取れた内容をできるだけ正確に。"
    "要約や解説はせず、話された内容そのものだけを出力してください。"
)

DRAFT_PROMPT = (
    "以下は音声の文字起こしです。この内容からObsidianノートの下書きを作ってください。"
    "1行目にタイトルだけを書き、2行目以降に要点(3〜5個の箇条書き)と見出し付きの本文を続けてください。"
    "要約しすぎず、話された内容の詳細をできるだけ保持してください。\n\n---\n\n"
)


def _api_key():
    return os.environ.get("GEMINI_API_KEY")


def guess_mime(path):
    m, _ = mimetypes.guess_type(path)
    if m:
        return m
    ext = path.lower().rsplit(".", 1)[-1]
    return {
        "m4a": "audio/mp4", "mp3": "audio/mpeg", "wav": "audio/wav",
        "aac": "audio/aac", "ogg": "audio/ogg", "flac": "audio/flac",
        "mp4": "video/mp4",
    }.get(ext, "application/octet-stream")


def _upload_file(path, mime, *, post=requests.post, get=requests.get, sleep=time.sleep):
    """File API へのresumableアップロード。ACTIVEになるまで待ってfile_uriを返す。"""
    key = _api_key()
    size = os.path.getsize(path)
    start = post(
        f"{API}/upload/v1beta/files?key={key}",
        headers={
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime,
            "Content-Type": "application/json",
        },
        data=json.dumps({"file": {"display_name": os.path.basename(path)}}),
    )
    start.raise_for_status()
    upload_url = start.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise RuntimeError(f"アップロードURL取得失敗: {start.text}")
    with open(path, "rb") as f:
        up = post(
            upload_url,
            headers={
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
                "Content-Length": str(size),
            },
            data=f.read(),
        )
    up.raise_for_status()
    info = up.json()["file"]
    name, uri = info["name"], info["uri"]
    while info.get("state") == "PROCESSING":
        sleep(2)
        info = get(f"{API}/v1beta/{name}?key={key}").json()
    if info.get("state") != "ACTIVE":
        raise RuntimeError(f"ファイル処理失敗: {info.get('state')}")
    return uri, mime


def _build_part(path, mime, *, post=requests.post, get=requests.get, sleep=time.sleep):
    if os.path.getsize(path) < INLINE_THRESHOLD:
        with open(path, "rb") as f:
            b = base64.b64encode(f.read()).decode()
        return {"inline_data": {"mime_type": mime, "data": b}}
    uri, mime = _upload_file(path, mime, post=post, get=get, sleep=sleep)
    return {"file_data": {"mime_type": mime, "file_uri": uri}}


def _generate_with_retry(body, *, post=requests.post, sleep=time.sleep, first_model=MODEL):
    """flash→flash-liteの順で、各モデル最大5回まで429/500/503を指数バックオフでリトライ。"""
    key = _api_key()
    models = [first_model] + [m for m in (FALLBACK_MODEL,) if m != first_model]
    data = None
    last_error = None
    for model in models:
        for attempt in range(5):
            r = post(
                f"{API}/v1beta/models/{model}:generateContent?key={key}",
                headers={"Content-Type": "application/json"},
                data=json.dumps(body),
                timeout=600,
            )
            if r.status_code == 200:
                data = r.json()
                break
            if r.status_code in (429, 500, 503):
                last_error = f"{model} {r.status_code}"
                wait = 5 * (2 ** attempt)
                sleep(wait)
                continue
            raise RuntimeError(f"APIエラー {r.status_code}: {r.text[:500]}")
        if data:
            break
    if not data:
        raise RuntimeError(f"混雑が続いて処理できず。少し時間をおいて再実行してください。({last_error})")
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError):
        raise RuntimeError(f"応答の解析に失敗: {json.dumps(data)[:500]}")


def transcribe(path, *, post=requests.post, get=requests.get, sleep=time.sleep):
    """音声ファイル1つを文字起こしして本文を返す。"""
    if not _api_key():
        raise RuntimeError("GEMINI_API_KEY が未設定")
    if not os.path.exists(path):
        raise RuntimeError(f"ファイルが無い: {path}")
    mime = guess_mime(path)
    part = _build_part(path, mime, post=post, get=get, sleep=sleep)
    body = {
        "contents": [{"parts": [part, {"text": TRANSCRIBE_PROMPT}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 65536},
    }
    return _generate_with_retry(body, post=post, sleep=sleep)


def _ffmpeg_split(path, chunk_sec, workdir):
    """ffmpegで音声を chunk_sec 秒ごとに分割し、生成されたチャンクのパス昇順リストを返す。"""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    ext = Path(path).suffix.lstrip(".") or "m4a"
    pattern = str(workdir / f"chunk_%03d.{ext}")
    subprocess.run(
        [
            "ffmpeg", "-i", str(path),
            "-f", "segment", "-segment_time", str(chunk_sec),
            "-c", "copy", "-reset_timestamps", "1",
            pattern,
        ],
        check=True,
    )
    return sorted(str(p) for p in workdir.glob(f"chunk_*.{ext}"))


def transcribe_long(path, *, split=_ffmpeg_split, transcribe=transcribe, chunk_sec=1200):
    """長尺音声をffmpegで分割し、各チャンクを文字起こしして連結する。

    分割結果が1個以下ならファイル全体を直接 transcribe する。
    """
    import tempfile
    with tempfile.TemporaryDirectory() as workdir:
        chunks = split(path, chunk_sec, workdir)
        if len(chunks) <= 1:
            return transcribe(path)
        return "\n".join(transcribe(c) for c in chunks)


def draft_note(transcript, *, post=requests.post, sleep=time.sleep):
    """文字起こしからObsidianノートの下書き(title, body)を生成する。"""
    if not _api_key():
        raise RuntimeError("GEMINI_API_KEY が未設定")
    body = {
        "contents": [{"parts": [{"text": DRAFT_PROMPT + transcript}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 65536},
    }
    text = _generate_with_retry(body, post=post, sleep=sleep)
    lines = text.split("\n", 1)
    title = lines[0].strip()
    note_body = lines[1].lstrip("\n") if len(lines) > 1 else ""
    return title, note_body
