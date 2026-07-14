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
import time
import json
import base64
import mimetypes
import subprocess
import tempfile
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
    "与えられた音声の文字起こしから、Obsidianノートの下書きを作ってください。\n"
    "出力は必ず次の形式に厳密に従ってください:\n"
    "1行目: `TITLE: ` に続けて、内容を表す10〜30字程度の日本語タイトルだけを書く"
    "(「文字起こし」「音声」などの語は使わない)。\n"
    "2行目: 空行。\n"
    "3行目以降: 要点(3〜5個の箇条書き)と見出し付きの本文。\n"
    "前置き・挨拶・「以下は〜です。」のような説明文は一切付けないこと。"
    "1行目は必ず `TITLE: ` から始めること。"
    "要約しすぎず、話された内容の詳細をできるだけ保持してください。\n\n---\n\n"
)


def _api_key():
    return os.environ.get("GEMINI_API_KEY")


def _safe_request_error(e):
    """requestsの接続系例外をURL/APIキーを含まないRuntimeErrorに変換する。
    生の例外文字列は `?key={KEY}` を含むURLごとjournalctlに流れてしまうため。"""
    return RuntimeError(f"Gemini request failed: {type(e).__name__}")


def _check_status(resp, what):
    """resp.raise_for_status() の代わり。HTTPErrorのメッセージは
    `... for url: {resp.url}` の形で `?key=...` ごとURLを含んでしまうため、
    ステータスコードだけを含む安全なRuntimeErrorに変換する(resp.textも含めない=
    エコーされたURLが混入するリスクを避ける)。"""
    if resp.status_code >= 400:
        raise RuntimeError(f"Gemini {what} failed: HTTP {resp.status_code}") from None


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
    try:
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
    except requests.exceptions.RequestException as e:
        raise _safe_request_error(e) from None
    _check_status(start, "upload開始")
    upload_url = start.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise RuntimeError(f"アップロードURL取得失敗: {start.text}")
    try:
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
    except requests.exceptions.RequestException as e:
        raise _safe_request_error(e) from None
    _check_status(up, "upload送信")
    info = up.json()["file"]
    name, uri = info["name"], info["uri"]
    while info.get("state") == "PROCESSING":
        sleep(2)
        try:
            poll = get(f"{API}/v1beta/{name}?key={key}")
        except requests.exceptions.RequestException as e:
            raise _safe_request_error(e) from None
        _check_status(poll, "処理状態確認")
        info = poll.json()
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
            try:
                r = post(
                    f"{API}/v1beta/models/{model}:generateContent?key={key}",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(body),
                    timeout=600,
                )
            except requests.exceptions.RequestException as e:
                # 接続エラー(DNS/timeout/refused等)は一過性の可能性があるため、
                # 429/500/503と同様にバックオフしてリトライする。
                # 例外文字列にはURL(?key=...)が含まれうるのでログに残さない。
                last_error = f"{model} connection_error({type(e).__name__})"
                sleep(5 * (2 ** attempt))
                continue
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
    with tempfile.TemporaryDirectory() as workdir:
        chunks = split(path, chunk_sec, workdir)
        if len(chunks) <= 1:
            return transcribe(path)
        return "\n".join(transcribe(c) for c in chunks)


TITLE_MARKER = "TITLE:"
_TITLE_MAX_LEN = 60
_TITLE_TRUNCATE_LEN = 40


def _looks_like_preamble(line):
    """モデルが「以下は音声の文字起こしです。」のような前置きを
    (TITLE:マーカーなしで)1行目に出してきた場合の検出。"""
    s = line.strip()
    if not s:
        return False
    if "文字起こし" in s:
        return True
    if (s.startswith("以下は") or s.startswith("これは")) and s.endswith("です。"):
        return True
    return False


def _parse_title_and_body(text):
    """モデル出力からタイトルと本文を頑健に取り出す。

    - `TITLE: ...` マーカーがあればそこからタイトルを取り、続く空行を飛ばして本文とする。
    - マーカーが無ければ、前置き文(「以下は音声の文字起こしです。」等)を1行目から検出して
      読み飛ばし、その次の非空行をタイトルとする(旧来のフォールバック挙動)。
    - タイトルが空、または60字を超えて異常に長い場合は、ファイル名スラッグ(40字上限)に
      収まるよう先頭40字に切り詰める。
    """
    lines = text.lstrip("\n").split("\n")

    if lines and lines[0].strip().startswith(TITLE_MARKER):
        title = lines[0].strip()[len(TITLE_MARKER):].strip()
        rest = lines[1:]
    else:
        idx = 0
        if lines and _looks_like_preamble(lines[0]):
            idx = 1
            while idx < len(lines) and lines[idx].strip() == "":
                idx += 1
        title = lines[idx].strip() if idx < len(lines) else ""
        rest = lines[idx + 1:] if idx < len(lines) else []

    while rest and rest[0].strip() == "":
        rest.pop(0)
    note_body = "\n".join(rest)

    if not title:
        for l in note_body.split("\n"):
            if l.strip():
                title = l.strip()[:_TITLE_TRUNCATE_LEN]
                break
    elif len(title) > _TITLE_MAX_LEN:
        title = title[:_TITLE_TRUNCATE_LEN]

    return title, note_body


def draft_note(transcript, *, post=requests.post, sleep=time.sleep):
    """文字起こしからObsidianノートの下書き(title, body)を生成する。"""
    if not _api_key():
        raise RuntimeError("GEMINI_API_KEY が未設定")
    body = {
        "contents": [{"parts": [{"text": DRAFT_PROMPT + transcript}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 65536},
    }
    text = _generate_with_retry(body, post=post, sleep=sleep)
    return _parse_title_and_body(text)
