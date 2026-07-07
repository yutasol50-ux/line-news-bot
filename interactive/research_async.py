#!/usr/bin/env python3
"""自己昇格ディスパッチャ(打つ=LINE webhook / 喋る=/capture の両入口で共通)。

全メッセージを Hermes に渡し、まず threshold_s 秒だけ待つ。
- 間に合えば → その場で即答(今まで通りの体験)。
- 超えたら → 「調べとくね」と即返し、裏で完走を待ち、Gmail に全文＋LINE に要点を push。

「待つのは最初の数十秒だけ、超えたらパスして手を離す」= 事前のキーワード判定は不要。
速いものは速く、重いものは自動で裏に回る。ノブは threshold_s ひとつ。

入口の違いは「即答の返し方」だけ:
- webhook: reply_token で reply() する( handle )
- /capture: HTTP レスポンスの文字列を return する( handle_capture )
配達(Gmail+LINE要点)ロジックは _finish_delivery で共通化。
"""
import threading

from interactive import hermes_brain
from interactive import research_delivery
from shared import line_client

# 昇格までの待ち時間(秒)。使いながら調整可。
DEFAULT_THRESHOLD_S = 35.0       # 打つ(LINE): reply_token有効期間内に収める
CAPTURE_THRESHOLD_S = 15.0       # 喋る(/capture): 端末の前で待つので短め
# 裏で走らせる時の絶対上限(秒)。資料屋の max_iterations が実質の頭打ちで、これは保険。
_LONG_TIMEOUT = 900

_PROMOTE = "📋 じっくり調べるね。終わったらここに送るよ（全文はメールにも届く）"
_PROMOTE_SPOKEN = "うん、調べとくね。終わったらLINEに送るよ！"
_FAIL = "ごめん、調べ物の途中でつまずいた。もう一回頼んでみて。"


def _title_from(text: str) -> str:
    body = text.strip()
    first = body.splitlines()[0] if body else ""
    return first[:40] or "調査レポート"


def _start_ask(text: str, session_id: str, ask):
    """ask をワーカースレッドで開始し (result, done) を返す。"""
    result: dict = {}
    done = threading.Event()

    def _work():
        try:
            result["report"] = ask(text, session_id, timeout=_LONG_TIMEOUT)
        except Exception as e:  # ask は自前で握るが保険
            result["error"] = e
        finally:
            done.set()

    threading.Thread(target=_work, daemon=True).start()
    return result, done


def _finish_delivery(text: str, result: dict, push, deliver) -> str:
    """完走した result を Gmail 配達＋LINE 要点 push する。戻り値=経路。"""
    report = result.get("report")
    if not report:
        push(_FAIL)
        return "async_error"
    title = _title_from(text)
    summary, md_path, email_ok = deliver(title, report)
    if email_ok:
        push(f"📋「{title}」調べ終わったよ！\n\n{summary}\n\n📧 全文はメールに送ったよ")
    else:
        push(f"📋「{title}」調べ終わったよ！\n\n{summary}\n\n⚠️ メール送信に失敗（全文は保存済み: {md_path}）")
    return "async"


def handle(
    text: str,
    reply_token: str,
    session_id: str = "line-owner",
    *,
    threshold_s: float = DEFAULT_THRESHOLD_S,
    ask=hermes_brain.ask,
    reply=line_client.reply,
    push=line_client.push,
    deliver=research_delivery.deliver,
) -> str:
    """打つ経路(LINE webhook)。戻り値=経路('inline'|'async'|'async_error')。"""
    result, done = _start_ask(text, session_id, ask)

    if done.wait(threshold_s):
        reply(reply_token, result.get("report") or hermes_brain._SAFE)
        return "inline"

    # 時間超過 → 昇格。まだ有効な reply_token で一言返し、裏で完走を待つ(この呼びは
    # webhook から別スレッドで走っているので何分でもブロックしてよい)。
    reply(reply_token, _PROMOTE)
    done.wait()
    return _finish_delivery(text, result, push, deliver)


def handle_capture(
    text: str,
    session_id: str = "line-owner",
    *,
    threshold_s: float = CAPTURE_THRESHOLD_S,
    ask=hermes_brain.ask,
    push=line_client.push,
    deliver=research_delivery.deliver,
) -> tuple:
    """喋る経路(/capture)。戻り値=(spoken_reply, route)。

    HTTP レスポンスを即返す必要があるので、昇格時は配達を別スレッドに逃がして
    「調べとくね」を即 return する。完走後の Gmail+LINE要点 はそのスレッドが行う。
    """
    result, done = _start_ask(text, session_id, ask)

    if done.wait(threshold_s):
        # 間に合った → その場の答えを喋って返す
        return (result.get("report") or hermes_brain._SAFE), "inline"

    # 時間超過 → 「調べとくね」を即返し、配達は裏スレッドへ
    def _deliver_later():
        done.wait()
        _finish_delivery(text, result, push, deliver)

    threading.Thread(target=_deliver_later, daemon=True).start()
    return _PROMOTE_SPOKEN, "async"
