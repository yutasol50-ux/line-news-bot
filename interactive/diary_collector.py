#!/usr/bin/env python3
"""日記モード中のLINEメッセージを捌くオーケストレータ。

webhookが呼ぶ入口。state(下書き)・classify(意図)・compose(清書)・store(保存)を束ね、
LINEへ返信する。Hermesにはファイルを一切触らせない(ここで完結)。
全経路で必ず何か返信し、無反応にしない。
"""
from datetime import datetime, timezone, timedelta

from interactive import diary_state as _state
from interactive import diary_classify
from interactive import diary_compose
from interactive import diary_store as _store
from interactive import line_media
from interactive.vision import read as _vision_read
from shared import line_client

_JST = timezone(timedelta(hours=9))

_GREETING = "日記モードにするね📔 今日はどうだった? 書き終わったら「終わり」って言ってね。"
_ASK = "メモしたよ📔 これでいい?(まだ書くなら続けてね)"
_NUDGE = "うん、どうぞ✍️"
_SAVED = "保存したよ📔 また明日ね"
_REOPEN = "じゃあ続き書いてね。あとで「これでいい?」でまとめるよ"
_PHOTO_OK = "写真もらったよ📸 これでいい?(まだ書くなら続けてね)"
_PHOTO_FAIL = "写真うまく受け取れなかった…もう一回送ってくれる?"


def _now() -> str:
    return datetime.now(_JST).isoformat(timespec="seconds")


def _entry_from_composed(state, composed: dict, now: str) -> dict:
    date = state.date()
    return {"date": date, "title": composed.get("title", date),
            "tags": composed.get("tags", []), "body": composed.get("body", ""),
            "raw": state.raw(), "photos": state.photos(),
            "created": now, "updated": now}


def handle_text(text, reply_token, *, now=None, classify=diary_classify.classify,
                compose=diary_compose.compose, store=_store, state=_state,
                reply=line_client.reply) -> str:
    now = now or _now()
    label = classify(text)
    ph = state.phase()

    if ph == "confirming":
        if label == "affirm":
            entry = _entry_from_composed(state, state.composed(), now)
            store.save(entry)
            state.clear()
            reply(reply_token, _SAVED)
            return "saved"
        # reject / content / more は下書きへ戻して続行
        if label == "content":
            state.append_text(text, now=now)
        state.reopen(now=now)
        reply(reply_token, _REOPEN)
        return "reopened"

    # collecting
    if label == "affirm":
        composed = compose(state.raw(), state.captions(), date=state.date())
        state.set_confirming(composed, now=now)
        reply(reply_token, f"こんな日記にしたよ📔\n\n{composed['body']}\n\nこれでいい?")
        return "confirm_shown"
    if label == "more":
        reply(reply_token, _NUDGE)
        return "nudge"
    # content
    state.append_text(text, now=now)
    reply(reply_token, _ASK)
    return "appended"


def handle_photo(message_id, reply_token, *, now=None,
                 fetch=line_media.fetch_content, read=_vision_read,
                 store=_store, state=_state, reply=line_client.reply) -> str:
    now = now or _now()
    try:
        data, content_type = fetch(message_id)
    except Exception as e:
        print(f"[ERROR] diary_collector photo fetch: {e}")
        reply(reply_token, _PHOTO_FAIL)
        return "photo_fail"
    caption = ""
    try:
        caption = read(data, content_type) or ""
    except Exception as e:
        print(f"[WARN] diary_collector caption: {e}")
    filename = store.save_photo(state.date(), data)
    state.append_photo(filename, caption, now=now)
    reply(reply_token, _PHOTO_OK)
    return "photo_added"


def finalize_timeout(*, now_iso, cutoff_hour=2, compose=diary_compose.compose,
                     store=_store, state=_state) -> bool:
    """activeな下書きが「別日 or 当日cutoff_hour超え」なら自動清書・自動保存。"""
    if not state.is_active():
        return False
    last = state.last() or ""
    now_date = now_iso[:10]
    entry_date = state.date() or now_date
    now_hour = int(now_iso[11:13]) if len(now_iso) >= 13 else 0
    stale = (entry_date < now_date) or (last[:10] < now_date and now_hour >= cutoff_hour)
    if not stale:
        return False
    composed = compose(state.raw(), state.captions(), date=entry_date)
    entry = _entry_from_composed(state, composed, now_iso)
    store.save(entry)
    state.clear()
    print(f"[INFO] diary finalize_timeout saved {entry_date}")
    return True


def start_manual(reply_token, *, now=None, state=_state, start=None,
                 reply=line_client.reply) -> str:
    """ユーザーが明示的に「日記」等で日記モードを開始した時の入口。"""
    now = now or _now()
    today = now[:10]
    starter = start or state.start
    starter(today, now=now)
    reply(reply_token, _GREETING)
    return "started"
