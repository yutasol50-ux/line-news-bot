"""自己昇格ディスパッチャ research_async.handle の経路テスト。

依存(ask/reply/push/deliver)は全て注入して、時間ベースの分岐だけを検証する。
"""
import time

from interactive import research_async as ra


def _capturing():
    calls = {"reply": [], "push": [], "deliver": []}

    def reply(rt, msg):
        calls["reply"].append((rt, msg))
        return True

    def push(msg):
        calls["push"].append(msg)
        return True

    def deliver(title, report):
        calls["deliver"].append((title, report))
        return ("要点サマリ", "/tmp/x.md", True)

    return calls, reply, push, deliver


def test_inline_when_fast():
    """threshold内に返れば その場でreply、pushもdeliverも無し。"""
    calls, reply, push, deliver = _capturing()

    def ask(text, sid, timeout):
        return "スイスの首都はベルンです"

    route = ra.handle("スイスの首都は?", "RT1", threshold_s=1.0,
                      ask=ask, reply=reply, push=push, deliver=deliver)

    assert route == "inline"
    assert calls["reply"] == [("RT1", "スイスの首都はベルンです")]
    assert calls["push"] == []
    assert calls["deliver"] == []


def test_promote_when_slow():
    """thresholdを超えたら 昇格メッセージをreply → 完走後にdeliver＆要点push。"""
    calls, reply, push, deliver = _capturing()

    def ask(text, sid, timeout):
        time.sleep(0.25)  # threshold(0.05)超過
        return "# 格安SIM比較\n\n## 要点\n楽天が最安..."

    route = ra.handle("格安SIM比較して", "RT2", threshold_s=0.05,
                      ask=ask, reply=reply, push=push, deliver=deliver)

    assert route == "async"
    # 1発目は昇格メッセージ(即返し)
    assert calls["reply"][0][0] == "RT2"
    assert "じっくり" in calls["reply"][0][1]
    # deliver が呼ばれ、pushに要点とメール文言
    assert calls["deliver"] and calls["deliver"][0][0] == "格安SIM比較して"
    assert len(calls["push"]) == 1
    assert "要点サマリ" in calls["push"][0]
    assert "メール" in calls["push"][0]


def test_promote_email_fail_keeps_fulltext_path():
    """Gmail失敗(email_ok=False)でも 欠落させず 保存パスをpushする。"""
    calls, reply, push, _ = _capturing()

    def ask(text, sid, timeout):
        time.sleep(0.2)
        return "長いレポート本文"

    def deliver_fail(title, report):
        return ("要点", "/home/yuta/hermes_files/cowork/reports/x.md", False)

    route = ra.handle("○○を詳しく調べて", "RT3", threshold_s=0.05,
                      ask=ask, reply=reply, push=push, deliver=deliver_fail)

    assert route == "async"
    assert "失敗" in calls["push"][0]
    assert "x.md" in calls["push"][0]


def test_capture_inline_when_fast():
    """喋る経路: threshold内に返れば (答え,'inline') を即返し、pushもdeliverも無し。"""
    calls, _reply, push, deliver = _capturing()

    def ask(text, sid, timeout):
        return "ベルンだよ"

    spoken, route = ra.handle_capture("スイスの首都は?", threshold_s=1.0,
                                      ask=ask, push=push, deliver=deliver)

    assert route == "inline"
    assert spoken == "ベルンだよ"
    assert calls["push"] == []
    assert calls["deliver"] == []


def test_capture_promote_speaks_ack_then_delivers_in_background():
    """喋る経路: 超えたら即「調べとくね」を返し、裏で完走→deliver＆要点push。"""
    calls, _reply, push, deliver = _capturing()

    def ask(text, sid, timeout):
        time.sleep(0.2)
        return "# 比較レポート\n本文..."

    spoken, route = ra.handle_capture("○○比較して", threshold_s=0.05,
                                      ask=ask, push=push, deliver=deliver)

    assert route == "async"
    assert "調べとく" in spoken
    # 裏スレッドの完走を待つ(最大2秒)
    for _ in range(40):
        if calls["push"]:
            break
        time.sleep(0.05)
    assert calls["deliver"] and calls["deliver"][0][0] == "○○比較して"
    assert len(calls["push"]) == 1
    assert "要点サマリ" in calls["push"][0]


def test_async_error_when_empty_report():
    """空レポートなら async_error でフォールバック文をpush。"""
    calls, reply, push, deliver = _capturing()

    def ask(text, sid, timeout):
        time.sleep(0.2)
        return ""

    route = ra.handle("重い依頼", "RT4", threshold_s=0.05,
                      ask=ask, reply=reply, push=push, deliver=deliver)

    assert route == "async_error"
    assert calls["deliver"] == []
    assert len(calls["push"]) == 1
