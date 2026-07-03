# LINE News Bot 引き継ぎ情報

---

## 【2026-07-03】LINEの頭脳をHermes(Haiku)に一元化 — 稼働開始 ✅

LINEに送った予定・メモ・会話を、記憶ありのHermes(Claude Haiku)1体が受けて判断・応答し、
予定はGoogleカレンダー・メモはNotionに書く構成に切替えた。**現在 本運用ON**。
設計/計画: `docs/superpowers/{specs,plans}/2026-07-03-hermes-line-brain*.md`

### 何が動くか(実機検証済み)
- LINEで「明日15時に歯医者、入れといて」→ Googleカレンダーに簡潔な予定名で登録(発話コピペでない)
- LINEで「牛乳をメモして」→ Notionに保存
- 「予定あったっけ」→ Hermesがカレンダーを読んで回答 / 会話は記憶継続(session=line-owner)
- 朝5:30の通達・Telegram窓口は無傷(今回いじっていない)

### スイッチ / ロールバック
- `.env` の `HERMES_BRAIN=on`(Hermes) / `off`(既存Gemini経路 dispatch.handle)。
- 切替後は `systemctl --user restart secretary-webhook`。off→onどちらも即時・撤退可能(検証済み)。
- 接続情報(.env, git外): `HERMES_API_URL=http://localhost:8642/v1/chat/completions`, `HERMES_API_KEY`(=~/.hermes/.env の `API_SERVER_KEY` と同値)。
- 退避: `.env.bak.pre-hermesbrain`。

### 構成メモ(重要・計画から変更した点)
- Hermes api_server(`~/.hermes/.env` の `API_SERVER_*`, port 8642, localhostのみ)を有効化。
- LINE→Hermes配線: `interactive/hermes_brain.py`。スイッチ: `interactive/server.py` の `_process`。
- Hermesツール(予定/メモ)のロジック: `hermes_tools/{calendar_tool,memo_tool}.py`(cli経由でline-news-botのactionを再利用)。CLI入口: `interactive/actions/cli.py`。
- **Hermesへの登録は `hermes_tools/line_secretary_tools.py`(アダプタ)を `~/.hermes/hermes-agent/tools/` へ flat symlink する方式**。
  - ⚠️計画当初の「ディレクトリごとsymlink」は不可: `discover_builtin_tools` の glob は非再帰、`_module_registers_tools` は **module直下の `registry.register(...)` のみ**検出(try/if包みは拾わない)。アダプタは必ずmodule直下でregisterする。
  - config: `~/.hermes/config.yaml` の `platform_toolsets.api_server: [clarify, memory, line_secretary]`。退避 `config.yaml.bak.pre-linesecretary`。
- 余談: 同じtry包み問題で `~/project/claude-hermes-bridge` の `board_tool`/`claude_tool` も実は未ロードだった(要同方式で修正)。

### 残課題(将来スコープ)
- 画像・音声など添付入力は未対応(別スコープ)。
- セッションのリセット手段(`/new`相当)は未実装。当面 session_reset(config: at_hour 4 / idle 24h)に任せる。

---

## 現在の状態
- LINEチャットボット（Cohere AI）: 稼働中
- LINEニュースボット: 基盤完成、fetchテスト待ち

## 環境
- LINE公式アカウント: @308zdoqo
- LINE User ID: U0002ff96706bbda0158fbb7d129f828d
- Render URL: https://line-bot-c17j.onrender.com

## GitHubリポジトリ
- チャットボット: yutasol50-ux/line-bot (Renderで動作中)
- ニュースボット: yutasol50-ux/line-news-bot (WSL2のcronで動作予定)

## ローカルパス
- チャットボット: /home/yuta/line-bot
- ニュースボット: /home/yuta/line-news-bot
- 旧Gemma版（触らない）: /home/yuta/news-delivery-system

## ニュースボットの構成
- RSS → Cohere(command-r-plus) で要約 → LINE Push API で送信
- カテゴリ: economy(経済) / work(仕事) / english(英語学習)
- .envファイル設定済み

## 次のステップ
1. `cd /home/yuta/line-news-bot && python3 news_delivery.py fetch` でニュース取得テスト
2. `python3 news_delivery.py send economy` で送信テスト
3. cronの設定（setup_cron.shを修正）

## cronスケジュール（予定）
- 03:00 JST: fetch
- 06:00 JST: send english
- 07:00 JST: send economy
- 08:00 JST: send work
