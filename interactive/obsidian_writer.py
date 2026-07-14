import os, re

def _slug(title, today):
    s = re.sub(r"[\\/:*?\"<>|\n\r]", "", title).strip()[:40] or "voicememo"
    return f"{today}-{s}"

def write_draft(title, body, transcript, message_id, *, inbox, today):
    os.makedirs(inbox, exist_ok=True)
    base = _slug(title, today)
    path = os.path.join(inbox, base + ".md")
    n = 2
    while os.path.exists(path):
        path = os.path.join(inbox, f"{base}-{n}.md"); n += 1
    fm = (
        "---\n"
        "tags: [voicememo, 要清書]\n"
        f"created: {today}\n"
        "source: LINE音声 → Gemini(自動下書き)\n"
        "status: draft\n"
        f"message_id: {message_id}\n"
        "---\n\n"
    )
    content = f"{fm}# {title}\n\n{body}\n\n## 全文（Gemini文字起こし）\n\n{transcript}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
