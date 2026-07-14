"""Telegram承認ポーラー(telegram_approval_poller)のユニットテスト。
ネットワークは全て注入(get/answer/reply)してモックし、実HTTPは叩かない。
"""
from interactive import telegram_approval_poller as poller


def _msg_update(update_id, text, chat_id):
    return {"update_id": update_id, "message": {
        "message_id": 1, "text": text, "chat": {"id": chat_id},
    }}


def test_handle_update_authorized_ok_forwards_and_replies():
    answers = []
    replies = []

    def fake_answer(text):
        answers.append(text)
        return {"handled": True, "status": "done", "message": "✅ 送信しました（1. Yes）"}

    def fake_reply(message):
        replies.append(message)

    update = _msg_update(10, "OK", "999")
    poller.handle_update(update, answer=fake_answer, reply=fake_reply, allowed_chat="999")

    assert answers == ["OK"]
    assert replies == ["✅ 送信しました（1. Yes）"]


def test_handle_update_unauthorized_chat_ignored():
    answers = []
    replies = []
    update = _msg_update(11, "OK", "666")  # not the allowed chat
    poller.handle_update(update, answer=lambda t: answers.append(t),
                          reply=lambda m: replies.append(m), allowed_chat="999")
    assert answers == []
    assert replies == []


def test_handle_update_not_handled_stays_silent():
    replies = []

    def fake_answer(text):
        return {"handled": False, "status": None, "message": ""}

    update = _msg_update(12, "こんにちは", "999")
    poller.handle_update(update, answer=fake_answer,
                          reply=lambda m: replies.append(m), allowed_chat="999")
    assert replies == []


def test_handle_update_no_message_ignored():
    calls = []
    update = {"update_id": 13, "some_other_field": True}
    poller.handle_update(update, answer=lambda t: calls.append(t),
                          reply=lambda m: None, allowed_chat="999")
    assert calls == []


def test_handle_update_edited_message_supported():
    answers = []
    update = {"update_id": 14, "edited_message": {"text": "y", "chat": {"id": "999"}}}
    poller.handle_update(update, answer=lambda t: answers.append(t) or {"handled": False},
                          reply=lambda m: None, allowed_chat="999")
    assert answers == ["y"]


def test_poll_once_returns_new_offset_and_updates():
    payload = {
        "ok": True,
        "result": [
            {"update_id": 10, "message": {"text": "a", "chat": {"id": 1}}},
            {"update_id": 11, "message": {"text": "b", "chat": {"id": 1}}},
        ],
    }
    calls = []

    class FakeResp:
        def json(self):
            return payload

    def fake_get(url, **kw):
        calls.append((url, kw))
        return FakeResp()

    new_offset, updates = poller.poll_once(5, get=fake_get)
    assert new_offset == 12
    assert updates == payload["result"]
    assert calls[0][1]["params"]["offset"] == 5


def test_poll_once_no_updates_keeps_offset():
    class FakeResp:
        def json(self):
            return {"ok": True, "result": []}

    new_offset, updates = poller.poll_once(7, get=lambda url, **kw: FakeResp())
    assert new_offset == 7
    assert updates == []
