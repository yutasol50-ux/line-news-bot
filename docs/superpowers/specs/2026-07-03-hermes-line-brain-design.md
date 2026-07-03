# LINEの頭脳をHermesに一元化する設計

作成: 2026-07-03 / 状態: **設計確定(ブレスト承認済み)**

## これは何 / なぜやるのか

本来やりたかったのは「LINEで本物のHermesエージェントに秘書として何でも頼む」こと。
だがHermesにLINEの差し込み口(プラグイン)が無く実現できなかったため、**簡易版**として
Gemini頭脳のLINE秘書(予定登録・メモ・朝の通達)を先に作った。順序が逆だった。

いまHermesの頭脳が **Claude Haiku** に載った(¥1000/月の上限つき)ことで、本命に進める条件が整った。
本設計は、**LINEに話しかける相手をGeminiからHermes(Haiku)1体に置き換える**。

### 解決したい具体の不満
- **犯人の切り分け不能**を避ける: 頭脳を2体同居させると不具合時に「Hermesか Geminiか」分からなくなる。→ **1体に統一**して常に犯人をHermesに固定。
- **Geminiのバカ正直コピペ**: 「明日◯◯の予定書いといて」で発話をそのまま予定名にしてしまう。→ Hermesが**要約して適切な予定名**を付ける。
- **枠焼けの再発**: 過去に Gemini⇄Claude のAI×AIループで無料枠を焼いた。→ 本設計は **人間×AI1体**でループ構造が無く、頭脳はHaiku(有料・上限¥1000)でGeminiを使わない。

## ゴール(この設計のスコープ)

> 君がLINEに送った**予定でもメモでも会話でも**、Hermes(Haiku・記憶あり)が受けて判断し、
> 予定はGoogleカレンダー、メモはNotionに書き、「あの予定なんだっけ」にはカレンダーを読んで答え、
> ただの相談・調べ物にはそのまま答えて、LINEに返す。
> 既存の受信・送信・朝の通達は壊さず、気に入らなければ設定1行でGeminiに戻せる。

## 非ゴール(YAGNI)

- **朝5:30の通達**は現状のまま。今回いじらない(決まった内容を流すだけで綺麗に動いている)。
- Hermesの**純正LINEアダプタ(道A)は作らない**。既存webhookを流用する(道B)。画像・音声など添付入力は将来の別スコープ。
- Telegram窓口は**廃止しない**。並存可能。今回は触らない。
- 保管先をHermes独自ストレージに一元化しない。**Googleカレンダー & Notionを維持**(ユーザーが自分の目でファクトチェックできることが要件)。

## 方針の要点(ブレストで確定した判断)

| 論点 | 決定 | 理由 |
|---|---|---|
| 頭脳 | Hermes(Haiku)1体。Gemini退場 | 犯人の切り分け可能性。霧を晴らす |
| 窓口の一元化 | あり(全部LINEでHermesに) | 秘書として一箇所に頼みたい |
| 保管先 | Googleカレンダー & Notion 維持 | 自分の目でも確認したい(ファクトチェック)。スマホのカレンダー習慣を失わない |
| 確認手段 | ①Hermesに聞く ②自分でカレンダー/Notionを見る の両立 | 同一データを二経路で見る |
| 繋ぎ方 | 道B(既存webhook流用)+ Hermes api_server | 受信・送信は完成品を再利用。記憶を継続 |
| 記憶 | あり(セッション継続) | 「さっきの話」を覚えた秘書 |
| 安全弁 | スイッチ1個でGeminiに即戻し | ロックイン回避・撤退可能 |

## アーキテクチャ / データフロー

```
君 → LINE
      │
      ▼
[既存 interactive/server.py]        受信・署名検証・重複排除(webhookEventId)は現状流用
      │  スイッチ: HERMES_BRAIN=on/off
      ├─ off → 既存 dispatch.handle()(Gemini intent)  ← ロールバック用に温存
      └─ on  → 新 hermes_brain.ask(text, session_id)
                    │  localhost:8642 /v1/chat/completions へPOST
                    │  ヘッダ X-Hermes-Session-Id = 固定ID(記憶継続)
                    ▼
             [Hermes api_server → Haiku頭脳]
                    │  自分で判断し道具を呼ぶ
                    ├─ 予定登録   → calendar 道具 → calendar_add.add() → Googleカレンダー
                    ├─ メモ       → memo 道具     → notion_memo.add()  → Notion
                    ├─ 予定照会   → calendar 道具(読) → calendar_events.get_calendar_block()
                    └─ 会話/相談/調べ物 → そのまま応答
                    ▼
             返答テキスト
      │
      ▼
[既存 line_client.reply()/push()] → LINEに返信(現状流用)
```

## コンポーネント

### 1. `interactive/server.py`(既存・小改修)
- 受信・署名検証・重複排除・非同期処理は**現状のまま**。
- `_process()` 内の頭脳呼び出しを**スイッチ化**:
  `HERMES_BRAIN`(.env)が `on` なら `hermes_brain.ask()`、それ以外は既存 `dispatch.handle()`。
- 返信は既存 `line_client.reply()` を使用(変更なし)。

### 2. `interactive/hermes_brain.py`(新規・薄い配線)
- 責務: テキストとセッションIDを受け取り、Hermes api_server にPOSTして応答文字列を返すだけ。
- 入口: `ask(text: str, session_id: str) -> str`
- 依存: `HERMES_API_URL`(既定 `http://localhost:8642/v1/chat/completions`)、`X-Hermes-Session-Id`、必要ならローカル認証トークン(api_server設定に合わせる)。
- 失敗時: 例外を投げず「ごめん、いま調子が悪いみたい」等の**安全な定型文**を返す(既存 dispatch と同じ流儀)。

### 3. Hermes側の道具ラッパー(新規・2本)
Hermesが予定/メモを扱えるように、既存スクリプトを**Hermesの道具として登録**する。
- `calendar_tool`(登録/照会): `calendar_add.add()` と `calendar_events.get_calendar_block()` を呼ぶ。
- `memo_tool`: `notion_memo.add()` を呼ぶ。
- **実行方式(推奨)**: 認証情報・依存を line-news-bot 側に留めるため、Hermes道具から
  line-news-bot の venv/env へ **subprocess で薄く呼び出す**(直import はHermes venvに依存を持ち込むため避ける)。
  - 例: `~/line/line-news-bot/venv/bin/python -m interactive.actions.calendar_add ...`(引数はJSONで受け渡し)
- 既存関数のシグネチャ(再利用対象):
  - `calendar_add.add(title, start_iso, end_iso=None, all_day=False) -> str`
  - `notion_memo.add(content, tags=None, when_iso=None) -> str`
  - `calendar_events.get_calendar_block() -> str`(読み取り。iCal URL経由)

### 4. Hermes設定(config.yaml)
- `api_server` プラットフォームを有効化(localhostのみ、必要ならローカル認証)。
- 既定頭脳が `claude-haiku-4-5`、月上限¥1000 は既存の設定を踏襲(本設計で変更しない)。
- 変更前に `config.yaml` を `.bak` 退避(既存の慣習)。

## 記憶(セッション)設計
- LINEのオーナー(君)からの会話は**固定のセッションID**(例 `line-owner`)を `X-Hermes-Session-Id` に載せる。
- これによりHermesは**前のやり取りを覚えたまま**応答できる(「さっきの件だけど」が通じる)。
- セッションの寿命/リセット方針は実装計画で詰める(当面は継続で開始、必要なら `/new` 相当のリセット手段を用意)。

## エラー処理 / 安全性
- **頭脳呼び出し失敗**: `hermes_brain.ask()` は例外を外に出さず定型文を返す。LINEが無反応にならない。
- **道具実行失敗**(カレンダー/Notion): 既存 dispatch と同様、「登録に失敗した」旨を返す。Hermesは失敗を握りつぶさず君に伝える。
- **コスト暴走**: Haikuの月¥1000上限で強制停止(既存ガード)。Geminiは使わないため無料枠焼けは構造的に発生しない。
- **多重処理**: 既存の `webhookEventId` 重複排除をそのまま利用。
- **切り分け**: 頭脳はHermes1体のみ。不具合時の責任所在が常に明確。

## ロールバック(撤退可能性)
- `.env` の `HERMES_BRAIN=off` + webhookサービス再起動で**即座にGemini経路へ復帰**。
- Hermes側の道具・api_server設定は残置(眠らせるだけ)。コード削除不要。
- 片道切符ではない。

## テスト / 受け入れ確認
1. **切替前**: 既存の予定登録・メモが通常どおり動くことを確認(退行がないベースライン)。
2. **api_server 単体**: `curl` で `localhost:8642/v1/chat/completions` に投げ、Hermesが応答することを確認。
3. **配線**: `hermes_brain.ask("テスト", "line-owner")` が応答文字列を返す。
4. **実機(予定)**: LINEで「明日15時に歯医者、入れといて」→ Googleカレンダーに**適切な予定名で**登録される(スマホで目視)。
5. **実機(照会)**: LINEで「来週なんか予定あった?」→ Hermesがカレンダーを読んで答える。
6. **実機(メモ)**: LINEで「◯◯メモしといて」→ Notionに保存される(目視)。
7. **実機(会話)**: 予定でもメモでもない相談に、記憶を保ったまま答える。
8. **ロールバック**: `HERMES_BRAIN=off` で再起動 → 既存Gemini挙動に戻ることを確認。
9. **朝の通達**: 変更後も5:30通達が従来どおり届く(無傷確認)。

## 実装計画で詰める未決事項
- api_server のローカル認証(共有シークレット)の要否と設定方法。
- Hermes道具の登録作法(`registry.py` への登録、`.bak` 退避、gateway再起動手順)。
- セッションのリセット手段(必要になったら)。
- subprocess呼び出し時の引数受け渡し(JSON)と、既存 action スクリプトへの薄い CLI 入口の追加要否。

## 参考(既存資産の場所)
- 受信: `~/line/line-news-bot/interactive/server.py`
- 現頭脳(退避対象): `~/line/line-news-bot/interactive/dispatch.py` / `intent.py`
- 予定書込: `~/line/line-news-bot/interactive/actions/calendar_add.py`
- メモ書込: `~/line/line-news-bot/interactive/actions/notion_memo.py`
- 予定読取: `~/line/line-news-bot/briefing/calendar_events.py`
- 送信: `~/line/line-news-bot/shared/line_client.py`
- Hermes: `~/.hermes/config.yaml` / `~/.hermes/hermes-agent/gateway/platforms/api_server.py` / `tools/registry.py`
