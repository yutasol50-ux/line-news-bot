# LINE対話秘書「書いたら実行」 設計書

作成日: 2026-06-28
対象: `/home/yuta/line/line-news-bot`(既存の朝の通達botを拡張)

## 1. 目的 / ゴール

LINEに日本語で書くだけで、秘書が**実際に手を動かす**。

- 最優先(B): 「明日14時に歯医者」→ Googleカレンダーに予定を**書き込む**
- 同(B): 「牛乳買う」「あの本のタイトル後で調べる」→ Notionのメモに**追記する**
- 継続(C): 朝5:30の通達は今のまま生かす(これで「先回り通知」も担保)

成功条件:
- LINEにメッセージを送ると、**PCの電源状態に関係なく**反応が返る(夜中・PCスリープ中でも)
- 予定が実際にGoogleカレンダーに入る / メモが実際にNotionに増える
- 実行結果がLINEで返ってくる(例:「📅 6/29 14:00 歯医者 を登録したよ」)
- 全部、現在ある無料の道具だけで回る(新規課金なし)

非ゴール(v2以降に回す):
- 「明日の予定教えて」等の**問い合わせ(読み取り)** ← まず書き込みを完成させる
- openclaw / hermes の利用(今回は使わない。将来「PC上で作業する相棒」として別途検討)

## 2. 全体構成

```
あなた(LINEアプリ)
   │  メッセージ送信
   ▼
[Tailscale Funnel]  ← WSL内サーバーを無料で公開(常時HTTPS)
   │  Webhook POST
   ▼
[受付係サーバー]  server.py (Flask)  ← WSL常駐・24時間起動
   │  署名検証 → 本文取り出し
   ▼
[Gemini頭脳]  intent.py (gemini-2.5-flash-lite, function calling)
   │  「文章」→「構造化アクション」に変換
   ▼
[実行役]  actions/
   ├ calendar_add.py  → Google Calendar API で予定を作成
   └ notion_memo.py   → Notion API でDBに行を追加
   │
   ▼
[返信]  reply.py  → LINE Reply API(無料・無制限)で結果を返す
```

### なぜこの構成か(代替案との比較)

- **クラウドにWebhookを置く案**: PC非依存で堅牢だが、ユーザーのPCは24/365稼働のため不要。ローカル完結の方が無料で道具も既存。→ 不採用
- **openclawを使う案**: 現状Claude前提・ローカル常駐型でLINE標準対応が弱く重い。Gemini×LINE×常時稼働には不向き。→ 不採用
- **採用案(ローカル完結)**: WSL常駐サーバー + Tailscale Funnel + Gemini + Notion/Calendar API。全部既存の無料資産。

## 3. 土台:WSL常時起動(秘書の心臓)

受付係はWSL内に常駐する。**WSLが落ちると秘書が無反応になる**(2026-06-28 日曜の通達取りこぼしと同じ原因 = Ubuntuの窓を閉じてWSLのVMが停止した)。

対策:WSLを「窓を閉じても・Windowsがスリープしても生き続ける」状態に固定する。

- 受付係を **systemd サービス**として登録(WSLのsystemd有効化が前提。`/etc/wsl.conf` の `[boot] systemd=true`)
- Windows側で **WSLを常時起動させる仕組み**(ログオン時に `wsl` を起動 + アイドルシャットダウン抑止)。詳細手順は実装計画で確定
- これにより朝の通達(cron/タスク)の安定も底上げされる

## 4. ディレクトリ整理

現状はファイルがフラットに並んでいる。役割で分ける。
**重要:** `secretary.py` の場所を変えると cron と Windowsタスクスケジューラの参照が壊れる。移動する場合は両方を必ず更新する(手順を §8 に明記)。

### 提案レイアウト

```
line-news-bot/                  # ※ディレクトリ名は据え置き(git/backup/cron互換のため。名は実態とズレるが許容)
├── briefing/                   # 朝の通達(既存をまとめる・push型)
│   ├── secretary.py            #   司令塔(当日1回ガード付き)
│   ├── calendar_events.py      #   カレンダー読み取り(iCal URL)
│   ├── weather.py
│   ├── news_headline.py
│   └── daily_word.py
├── interactive/                # 新規:対話秘書(webhook型)
│   ├── server.py               #   Flask Webhook受付 + LINE署名検証
│   ├── intent.py               #   Gemini: 文章→アクション(function calling)
│   ├── reply.py                #   LINE Reply API
│   └── actions/
│       ├── calendar_add.py     #   Google Calendar API 書き込み
│       └── notion_memo.py      #   Notion API 追記
├── shared/
│   └── line_client.py          # push/reply 共通の薄いLINEクライアント(既存 line_send.py を吸収)
├── data/                       # sent_state.json 等(据え置き)
├── logs/
├── docs/
├── venv/
└── .env
```

各ユニットの責務:
- `server.py`: HTTPを受けるだけ。署名検証して本文とreplyTokenをintentに渡す。ビジネスロジックを持たない。
- `intent.py`: 入力文字列を受け、`{action, params}` を返す純粋関数的な層。LINEもHTTPも知らない。
- `actions/*`: 1ファイル1外部サービス。`calendar_add.add(event)` / `notion_memo.add(memo)` のような明確なIF。
- `reply.py` / `shared/line_client.py`: LINE送受信の薄いラッパ。

## 5. データフロー(1リクエストの流れ)

1. LINEがWebhook URL(Tailscale Funnel)に `POST /webhook` を送る
2. `server.py` が `X-Line-Signature` を**チャネルシークレットで検証**(なりすまし防止)。失敗は400
3. イベントから `text` と `replyToken` を取り出す
4. `intent.py` がGeminiを呼ぶ。function calling で以下のいずれかに振り分け:
   - `add_calendar_event(title, start_datetime, end_datetime?)`
   - `add_memo(content, tags?)`
   - `none`(雑談・判断不能 → そのまま短く返信)
5. 該当アクションを実行:
   - `calendar_add.add(...)` → Google Calendar に insert
   - `notion_memo.add(...)` → Notion DB に行を追加
6. `reply.py` が結果文をReply APIで返信(**replyTokenは1回・約1分有効**)

### 日時の解釈
- 「明日14時」「金曜の朝」等の相対表現はGeminiにJST現在時刻を渡して**絶対日時(ISO8601, +09:00)**に解決させる
- 時刻が無い予定(「水曜 歯医者」)→ 終日予定として登録
- あいまいで解決不能な場合 → 登録せず「いつ?」と聞き返す(v1は簡易:1往復で諦め、登録せず確認文を返す)

## 6. 外部サービス連携

### 6.1 LINE Messaging API
- **受信**: Webhook。`server.py` で署名検証。チャネルシークレットが新たに必要(`.env` に `LINE_CHANNEL_SECRET`)
- **返信**: Reply API(`replyToken`使用)= **無料・無制限**。対話の返信は全てこれ
- **朝の通達**: 従来通り Push API(月200通まで無料、1日1通で十分)
- 既存の `LINE_ACCESS_TOKEN` / `LINE_USER_ID` はそのまま流用

### 6.2 Google Calendar API(新規・書き込み)
- 既存のGCPプロジェクト(TTS用)を流用。新規契約なし
- セットアップ(一回):
  1. Calendar API 有効化: https://console.cloud.google.com/apis/library/calendar-json.googleapis.com
  2. OAuthクライアント(デスクトップアプリ)作成: https://console.cloud.google.com/apis/credentials
  3. 認証情報JSONをDL → `.env` 外の安全な場所に配置(例:`~/line/line-news-bot/secrets/gcal_client.json`、gitignore)
  4. 初回認証フロー(承認リンクをクリックして許可)→ refresh token を保存
  5. WSLはループバック認証(TTSで実績あり)
- スコープ: `https://www.googleapis.com/auth/calendar.events`(イベント作成に必要な最小)
- 書き込み先カレンダー: プライマリ(または `.env` で指定可)

### 6.3 Notion API(新規・メモ追記)
- 「コネクト(旧:インテグレーション)」を作成済み。**トークン取得済み**
- 残作業(実装時):メモ用データベースを1個作成 → そのDBに作成済みコネクトを接続
- `.env` に `NOTION_TOKEN` と `NOTION_MEMO_DB_ID`
- DBスキーマ(最小):`名前`(title), `日付`(date), `タグ`(multi-select 任意)
- スマホ/PCのNotionアプリで即閲覧可

### 6.4 Gemini API
- `gemini-2.5-flash-lite`(無料枠が太い。2.5-flashは1日20リクエスト制限のため不採用)
- function calling でアクション抽出

## 7. エラーハンドリング

- 署名検証失敗 → 400、無視(攻撃/誤送信)
- Gemini呼び出し失敗 → 「ちょっと調子悪い、もう一回送って」と返信、ログ記録
- アクション実行失敗(Calendar/Notion APIエラー)→ 失敗を**正直に**LINE返信(例:「カレンダー登録に失敗。後で見て」)+ ログ
- replyTokenの期限切れ/二重 → Push APIにフォールバックして返信
- 各アクションは独立。片方失敗しても他方は実行(朝の通達と同じ思想)
- 秘密情報(トークン・認証JSON)は全て `.env` / `secrets/` に置き `.gitignore`。コードに直書きしない

## 8. 移行手順(整理に伴う必須作業)

ファイル移動で既存の朝の通達を壊さないため、以下を必ずセットで行う:

1. ファイルを `briefing/` 等へ移動
2. `briefing/secretary.py` 内の相対import / `Path(__file__).parent` 基準のパス(data/, .env)を検証・修正
3. **cron更新**: `crontab -e` の `secretary.py` パスを新パスへ
4. **Windowsタスクスケジューラ更新**: `LINE_Secretary_Briefing` の `wsl` 引数のパスを新パスへ(`C:\Users\yuwat\setup_line_task.ps1` を直して再登録)
5. 移動後、`secretary.py dry` と タスク手動実行で**通達が壊れていないこと**を確認してからコミット

## 9. テスト方針

- `intent.py`: 入力文 → 期待アクションのユニットテスト(モックGemini or 実呼び出し少数)。「明日14時に歯医者」「牛乳メモ」「こんにちは(none)」等の代表ケース
- `calendar_add` / `notion_memo`: テスト用カレンダー/DBへの実書き込みで疎通確認
- `server.py`: 署名検証の正常/異常、ダミーWebhook payloadで分岐確認
- E2E: 実LINEから1通送って、カレンダー/Notionに入り、返信が来るまでを手動確認

## 10. v1スコープ確定

含む:
- ✅ LINE受信(Webhook + Tailscale Funnel + WSL常駐)
- ✅ Gemini intent振り分け(calendar / memo / none)
- ✅ カレンダー書き込み / Notionメモ追記
- ✅ Reply APIで結果返信
- ✅ ディレクトリ整理 + cron/タスク参照更新
- ✅ 朝の通達は維持

含まない(v2):
- 予定の問い合わせ・一覧・変更・削除
- リマインド追加、複数往復の対話、添付/画像
- openclaw / hermes 連携
