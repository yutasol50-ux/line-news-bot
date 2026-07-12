# 一本化ワークフロー 構想の地図

- 日付: 2026-07-11
- ステータス: **リマインダー最小スライス実装済み・本番稼働（2026-07-11）**。以下は元の構想地図＋末尾に実装記録。
- 発端: 2026-07-09 朝、Hermesが「明日朝5時半に洗濯物と送る」とLINEで**明確に確約したのに送らなかった**事件。

## 実装記録（2026-07-11）— 洗濯機事件を構造的に解決

- **③台帳の結論が変わった: Google Tasks → Googleカレアンダー**。理由=実機検証で判明した2点:
  - **Apple リマインダーは CalDAV では書けない**。このApple ID(yuta19921231@yahoo.co.jp)のiCloudリマインダーは「アップグレード済み」で、CalDAV書き込みは端末に出ない幽霊リスト「リマインダー ⚠️」に落ちるだけ（Apple公式 HT210220 の placeholder todo がリスト内に存在＝確定）。→ Linuxサーバーから書く道は無い（Mac mini後の remindctl/EventKit まで封印）。
  - **Google Tasks は日付のみで時刻を持てない＋別スコープで再認証が必要**。→ 却下。
  - **Googleカレンダーが全条件クリア**: 既存 `calendar.events` スコープで書ける（再認証ゼロ）／時刻を正確に持てる／スマホで見れる。
- **④届けるは cron/Pushcut 不要になった**。カレンダー予定に `reminders.overrides=[{popup,0分前}]` を付ければ **iOSカレンダーが標準通知で自分で鳴らす**（実機で 17:18/17:38/17:45 の3回確認済）。Apple リマインダーで狙ってた「自分で鳴る」がそのまま実現。
- **新規実装 = `reminder_add` ツール1本**（既存 calendar_add/memo_add と同じ4層配線）:
  - `interactive/actions/calendar_add.py::add_reminder(text, at_iso)` — ⏰プレフィクス＋popup0分の短い予定を作る
  - `interactive/actions/cli.py` — `reminder_add` コマンド追加
  - `hermes_tools/calendar_tool.py` — `reminder_add()` ＋ `REMINDER_ADD_SCHEMA`
  - `hermes_tools/line_secretary_tools.py` — `registry.register(reminder_add, toolset=line_secretary, emoji=⏰)`
  - TDD 3件追加、全180テスト green。hermes-gateway 再起動で本番反映。
- **E2E検証**: api_server 経路に「5分後にゴミ出しをリマインドして」→ Hermesが自分で `reminder_add` を発火 → カレンダーに `⏰ゴミ出し`(popup0分) が実在するのを台帳側で確認（＝Hermesの返事を信じず台帳で裏取り）。テスト予定は掃除済み。
- **残（将来）**: 完了トラッキング/催促（見張り番）は未実装＝iOS通知が鳴って終わり。ネチネチ催促が要るなら既存 cron+Pushcut を足す。①入口のショートカット新設は別途（今は LINE/capture で足りる）。Mac mini後は Apple リマインダーへ remindctl で移行も可。

## 貫く第一原則

> **「Hermesは書記であり見張り番。台帳は外部アプリに置く」**

- Hermesが落ちても消えない。渡辺さん自身もスマホで直接見れる。
- だから **Hermesを100%信用しなくても成立する**。
- これは渡辺さんの信条（一本化・ロックイン回避・無料枠優先）と、洗濯機事件の教訓の両方から導かれた原則。

### 洗濯機事件の根本原因（調査で確定）

- Hermesの頭脳（Haiku）が自然文から実行できる手足は、コード上 `add_calendar_event`（Googleカレンダー）と `add_memo`（Notion）の**2つだけ**。
- 「指定タイミングで能動的に届ける＝リマインダー」という概念が、**入口（intent）にも出口（朝の通達）にも存在しない**。
- 朝の通達 `briefing/secretary.py` は カレンダー/天気/ニュース/一語 の**固定4ブロック**で、外から差し込む口が無い。
- 結果、Hermesは「✓送信します」と気持ちよく返事したが、裏で何もできず口約束が蒸発した。
- **渡辺さんの落ちでもHermesの怠慢でもなく、機能が最初から無かった。**

## 4層モデル

```
①入口   iPhoneメモ（音声・殴り書き、Apple Intelligenceで清書）
          └→ ショートカット（共有シート1タップ）─→ Hermesへ
              ▼
②頭脳    Hermes（Haiku）＝ 解釈して振り分ける「書記」＋ 未完了を見張る「見張り番」
              ▼
③台帳    ・予定       → Googleカレンダー（連携済・本命）
（残す）  ・タスク     → Google Tasks（同じGoogle認証・無料・ロックインなし）
          ・育てるメモ → Obsidian（将来Mac、今は素振り）
              ▼
④出口    ・日常の会話/依頼/報告 → LINE（既存・双方向）
（届ける）・「絶対見逃すな」の一撃 → Pushcut（課金済を活用＋ボタンでアクション）
```

## 「洗濯機」がどう確実になるか（ゴールの体験）

1. 渡辺さん「明日朝、洗濯物を回して」→ LINE or メモから
2. Hermesが **Google Tasks に書く**（＝消えない台帳に残る）
3. Hermesのcronが朝5:30に発火、**未完了を検知**
4. **Pushcut**で「洗濯物まだだよ」＋【完了】ボタン → 埋もれず届く
5. 【完了】タップ → タスクが消える

## 各アプリの結論（触った上での最終判断は保留）

| 論点 | 結論 | 理由 |
|---|---|---|
| Bark vs Pushcut | **Pushcutに集約** | Pushcutを既に月200円課金済＝上位互換。無料の下位版Barkを並べる意味がない |
| 通知はLINEで足りる？ | 日常はLINE、**強制通知だけPushcut** | LINEは優秀だが会話に埋もれる。埋もれたら困る一撃だけ専用チャンネルへ |
| iPhoneメモ vs Obsidian | 短期＝メモ（今すぐ）／長期＝Obsidian（将来Mac） | メモ＝瞬間の捕捉、Obsidian＝育てる第二の脳。WSL2では同期が難物、本領はMac |
| Appleリマインダー | **今回は不採用** | 通知が弱く、HermesからCalDAV経由で書きにくい |
| ショートカット | **全層を繋ぐ線**。まず①入口の1個だけ作る | 日記でウォッチ通知作成に苦戦した経緯あり→一気に作らず1個で成功体験を作る |

## Pushcut と Bark の違い（判断の根拠）

| | Bark | Pushcut |
|---|---|---|
| 本質 | 通知を出す蛇口（URL叩く→鳴る） | 通知を出す＋ボタンでアクション（ショートカット起動等） |
| 方向 | 一方通行 | 双方向（ボタン→ショートカット） |
| 料金 | 無料 | 月200円（**渡辺さんは課金済**） |
| 日本語通知 | ◎ | ◎ |

- 「いつ鳴らすか」はどちらも持たない → **Hermesのcronが担当**。通知アプリは「確実に届ける」だけ。
- ショートカットを使い込むほど、Pushcut＝「通知からショートカットを起動する着火装置」に純化する。

## 次に確かめること（＝まだ触っていない鍵）

- [ ] **ショートカット**「共有シート→Hermesへ」を1個作る（成功体験・①入口が完成）。一番使い、一番シンプルな所から。
- [ ] **Pushcut**：サーバーからURLを叩いて通知＋ボタンが動くか素振り
- [ ] **Google Tasks**：HermesのGoogle認証で書き込めるか確認

## 宿題：「残す」と「届く」は別（この設計doc自体で露呈した問題）

- 私（Claude）は毎回 `docs/` に設計を残してきたが、渡辺さんはスマホ生活のため**PC内のmdを一度も見れていなかった**。
- これは洗濯機事件と同じ構造：**確実に残しても、渡辺さんが見れる場所でなければ届いていないのと同じ。**
- 当面の対処：要点をLINEで送る（2026-07-11実施済み）。
- 仕組みとしての対処（設計に組み込む）：**Hermesが書いたdoc/メモを、スマホから見れる置き場（home-hub のページ or Google Docs）に自動で乗せる**。これはワークフローの③台帳の一部として扱う。

## 実装の順番（把握フェーズが終わってから）

1. Hermesに `add_reminder` / タスク書き込みの手足を足す（②頭脳の欠損を埋める）
2. 台帳（Google Tasks）への書き込み配線
3. Hermesのcronで未完了を監視 → Pushcutで通知
4. ショートカットで①入口を整える

※ 洗濯機の「明日朝5時半に洗濯物」がそのまま最初のテストケースになる。

## 将来Mac（M5）で化ける部分

- Mac + iCloud なら Obsidian同期が無料で自然に動く → WSL2で諦めた「Inboxフォルダ常時監視→ローカルLLM解析」が成立。
- Geminiの元案（メモ→Obsidian→監視）は「今のWSL2」では嘘だが「未来のMac」ではほぼ正解になる。
- だから **今はLINE/メモ入口で運用 → Mac移行時にObsidian入口へ差し替え** が正しい順番。

## スヌーズ/完了(Pushcut二段目)実装済み(2026-07-12)

`reminder_add` に加え、④届ける層を実装。**Pushcut通知＋完了/スヌーズボタン**。
- **配線**: ⏰カレンダー予定を台帳に、毎分cron `interactive/reminder_watch.py` が到来を検出→`shared/pushcut_client.notify_reminder`でPushcut通知。既配達は `interactive/reminder_store.py`(delivered/active)で管理。ボタン→`server.py` の `/reminder/done`(予定削除)・`/reminder/snooze?minutes=N`(N分先へ移動＋再発火)。認証=`REMINDER_TOKEN`(クエリ文字列可)。
- **A案採用**: `add_reminder` はカレンダー標準通知OFF(`overrides:[]`)。Pushcut一本で二重通知回避。
- **Pushcutの学び(実機で潰した)**:
  - `runOnServer:true` は専用Automation Server(iOS端末)が要りハングする→**不採用**。
  - 動的actions(API)は **Apple Watchにボタンが出ない**→**固定ボタン方式**(アプリの「reminder」通知に3ボタン事前登録・active操作・`urlBackgroundOptions`で端末裏実行)に決定。
  - **iPhoneでは完璧**(通知即時＋ボタンタップでスヌーズ0.8秒、実証)。**Apple Watchはボタン非表示が確定**(watchOSは他社アプリの通知アクションを出さない=Apple純正リマインダーのみ可能。設定でも回避不可)。
- **Watchの結論**: Watch=通知で気づくだけ、操作はiPhone。ユーザー合意で一旦ロックイン。

## 宿題(次回): Watch操作をLINE二段で(検証待ち)
- 発想(ユーザー): **Pushcut(速い・気づく)＋LINE(操作)を同時発射**。Watch版LINEなら返信できる=腕から音声/定型でスヌーズ→Hermesが動かす。
- **要実機確認(ユーザー)**: Watch版LINEの返信が ①🎤ディクテーション可 か ②定型文カスタム可 か。可なら二段実装(cronは流用、鳴らす先にLINE push追加＋Hermesが"アクティブなリマインダー"のスヌーズ/完了を理解)。不可ならWatchは気づき専用のまま。
- レイテンシ知見: Bark/PushcutはAPNs直行で速い、LINEはホップ多く体感遅い→速さはPushcut・操作はLINE、の役割分担が筋。
