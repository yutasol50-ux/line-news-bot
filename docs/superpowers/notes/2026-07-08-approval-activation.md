# Claude Code 遠隔承認 — 設置手順（Task 8）

有効化日: 2026-07-09。トークン値は記載しない（`.env` の `APPROVAL_TOKEN`）。

## 構成
- **フック**: `hooks/approval_notify_hook.py`（Claude Code の Notification フックが叩く）。
  `notification_type == "permission_prompt"` の時だけ、`APPROVAL_IDLE_SEC`(既定45)秒 sleep 後に
  pane を再確認し、まだ承認待ちなら `POST /approval/notify` する。
- **ラッパー**: `bin/cc` → `~/.local/bin/cc` に symlink。`tmux new-session -A -s claude "claude"` で
  Claude Code を常駐 tmux セッション内に起動する（send-keys 注入の前提）。
- **サーバ**: `interactive/server.py` の `/approval/notify`（登録+push）と `/webhook` postback 分岐（注入）。
- **設定**: `~/.claude/settings.json` の `hooks.Notification` に venv python でフックを登録。

## 設置コマンド（冪等）
```bash
cd ~/line/line-news-bot
chmod +x hooks/approval_notify_hook.py bin/cc
mkdir -p ~/.local/bin && ln -sf "$PWD/bin/cc" ~/.local/bin/cc
grep -q '^APPROVAL_TOKEN=' .env || echo "APPROVAL_TOKEN=$(python3 -c 'import secrets;print(secrets.token_hex(16))')" >> .env
grep -q '^APPROVAL_IDLE_SEC=' .env || echo "APPROVAL_IDLE_SEC=45" >> .env
systemctl --user restart secretary-webhook.service
```

`~/.claude/settings.json` の `hooks` に追加（SessionStart は残す）:
```json
"Notification": [
  { "hooks": [ { "type": "command",
    "command": "/home/yuta/line/line-news-bot/venv/bin/python3 /home/yuta/line/line-news-bot/hooks/approval_notify_hook.py" } ] }
]
```

## 注意 / 既知の前提
- `~/.local/bin` は PATH 上 `/usr/bin` より先。`cc` は tmux ラッパーに解決される（C コンパイラ `/usr/bin/cc` は `gcc` で呼ぶ）。
- 以前 `.bashrc` に置いた `alias cc='claude'` は撤去済み（alias が symlink を覆うため）。
- Claude Code は **tmux 内**で動いている必要がある（`cc` で起動すれば自動的に満たす）。
- サンドボックスで自動実行される読取系コマンドはそもそもプロンプトが出ない＝遠隔通知も飛ばない（正常）。
- 遠隔承認は全信頼・一段（破壊系も含めワンタップ承認可）。本人 `LINE_USER_ID` のみ受付、注入直前に pane 再検証で空振り防止。

## 検証済み（2026-07-09）
- Notification フック発火・`permission_prompt` 判別（[[findings]] 参照）。
- `/approval/notify`（実プロンプト）→ LINE クイックリプライ push 到達 → タップ postback 往復を確認。
- 全 152 テスト green。
- 残: 本物の承認待ちへの実注入（下記 E2E）。

## 手動 E2E 手順
1. `cc` で Claude Code を起動（tmux `claude` セッション）。
2. 書き込み/ネットワーク系コマンドを頼み承認プロンプトを出す。**席で答えず `APPROVAL_IDLE_SEC` 秒待つ。**
3. iPhone/Watch の LINE に「🔐 承認待ち … 1./2./3.」が届く。
4. ボタンをタップ → Claude Code 側にキー注入され続行、LINE に「✅ 送信しました」。
5. 空振り確認: 先にキーボードで答えてからボタンを押し「送りませんでした」が返る（注入されない）こと。
