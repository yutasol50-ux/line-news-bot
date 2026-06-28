# LINE対話秘書 セットアップ記録

完成日: 2026-06-29

## 構成

```
LINE → Tailscale Funnel → WSL常駐Flask(:8800) → Gemini → カレンダー/Notion → LINE返信
```

- 公開URL: `https://watanabeyuta-1.tail9c9905.ts.net/webhook`
- 受付係: `interactive/server.py`(systemdユーザーサービス `secretary-webhook.service` で常駐)
- 頭脳: Gemini `gemini-2.5-flash-lite`
- 実行役: `interactive/actions/calendar_add.py`(Googleカレンダー), `interactive/actions/notion_memo.py`(Notion DB)

## 常駐・公開の要点

- WSL常時起動: Windowsタスク `WSL_KeepAlive`(`C:\Users\yuwat\setup_wsl_keepalive.ps1`)
- systemd: `systemctl --user status secretary-webhook.service`、linger有効でログオフ後も稼働
- Tailscale Funnel: `tailscale funnel --bg 8800`(operator=yuta 設定済み、tailnetでFunnel有効化済み)

## .env キー(値は秘匿)

- `GEMINI_API_KEY` … 無料枠キー(`.bashrc` のものと同一。前払い課金プロジェクトのキーは429で使用不可だった)
- `LINE_CHANNEL_SECRET` … Webhook署名検証用
- `LINE_ACCESS_TOKEN` / `LINE_USER_ID` … 既存(push/reply共用)
- `NOTION_TOKEN` / `NOTION_MEMO_DB_ID` … メモDB「秘書メモ」(列: 名前/日付/タグ)。コネクト「LINE秘書」を接続済み
- `GOOGLE_CALENDAR_ID=primary`、`GCAL_CLIENT_SECRET_PATH` / `GCAL_TOKEN_PATH` … OAuth(同意画面は本番公開、scope: calendar.events)

## LINE Developers 設定

- Webhook URL: 上記の公開URL(末尾 `/webhook`。旧 `/callback` から変更)
- Webhookの利用: ON / 検証: 成功
- 応答メッセージ: OFF(秘書返信と競合させない)
- 旧 `line-bot`(Render, 👍/👎フィードバック)は役目を終え、本Webhookで上書き

## 運用メモ

- ログ: `journalctl --user -u secretary-webhook.service -f`
- 再起動: `systemctl --user restart secretary-webhook.service`
- 朝の通達(briefing/)は別系統(cron + Windowsタスク `LINE_Secretary_Briefing`)で継続
