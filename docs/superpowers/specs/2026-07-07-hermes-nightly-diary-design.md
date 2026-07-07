# 夜の日記（Hermes Nightly Diary） — 設計

作成日: 2026-07-07
関連: LINE秘書 Hermes化 / capture構想 / 写真・PDF入力（media_intake, vision.py）

## 芯（ユーザーの本当の欲求）

「日記を書きたいが、**日付分類などの整理が面倒**で続かない。夜にHermesから聞いてくれて、**書きっぱなしを勝手に綺麗に整理**してくれるなら続けられる。最初は箇条書き程度しか書かないが、**リズム／習慣になれば量を増やしたい**」。

低摩擦の入口（20時に聞かれる）＋書いた後の整理をHaikuに丸投げ、が続ける鍵。日記はユーザー個人の記録なので**清書は忠実（盛らない）**が絶対条件。

## スコープ

- **入る**: 20時のLINE声かけ → 会話しながら日記収集 → Haiku清書 → ローカル保存 → 本棚Webページで見返し。
- **入らない（別スペック）**: リマインダー/コーチ連携（別構想）、音声STT（Mac mini後）、Notion本格移行。
- **既に完了で不要**: web検索（2026-07-06に `web` toolset 開通済み・稼働確認済み）。

## 全体の流れ（ユーザー体験）

1. **20:00 JST**、cronがLINEへ push「今日どうだった?」→ **日記モード開始**（session `line-owner`）。
2. ユーザーが書く（箇条書きOK、写真も複数OK）。
3. Hermesが**毎回**、短いリアクション＋「これでいい?」で確認。
4. ユーザーの返信を Haiku が意図判定:
   - 追記/「まだ！」/そのまま書き進める → **下書きに貯め続ける**。
   - **肯定**（いいよ/終わり/おけ/ok/おk/とりあえず 等、キーワード一致でなく意味で判定）→ **清書フェーズへ**。
5. Haikuが下書き全体を**清書**（忠実に整えるだけ）→ **完成版をLINEで見せる**「こんな日記にしたよ📔 これでいい?」。
6. 再度**肯定** → **保存**「保存したよ📔」。否定/直し指示 → 収集に戻る。
7. **時間切れ**（当日 02:00 JST 到達 or 無操作Nターン）→ 貯まっている分を自動清書・自動保存（**書いたものは絶対に失わない**）。
8. 20時を逃した/別時間に書きたい場合、ユーザーが自分から「日記」と送れば**いつでも日記モード開始**。

「肯定なら何でも次へ進む」を全確認ポイント（収集中の「これでいい?」／清書後の「これでいい?」）で一貫適用する。

## コンポーネント（すべて `interactive/`, TDD）

境界を小さく保ち、既存の media_intake / summarize / hermes_brain と同じ「Hermesにファイル権限を与えず、ハンドラ側でテキスト化してから渡す」思想を踏襲する。

### `diary_state.py` — 日記モードの状態機械
- 役割: line-owner の日記下書きを保持する状態機械。`start()` / `append(text, photos)` / `classify_reply(text) -> {"more"|"affirm"|"reject"}` / `finalize()` / `is_active()` / `timeout_check(now)`。
- 意図判定 `classify_reply` はHaiku（`summarize.py`と同じMessages API直叩き）に「この返事は肯定か・まだ書き続けたいか・やり直しか」を短く聞く。失敗時は安全側（`more`＝勝手に確定しない）にフォールバック。
- 状態は**ファイル永続化**（`data/diary/_active.json`）。サーバ再起動で下書きが消えない。
- 依存: なし（純粋な状態＋Haiku判定の薄いラッパ）。

### `diary_compose.py` — 清書＋メタ生成（Haiku）
- 役割: 下書き（原文＋写真キャプション）を受け取り `{title, tags[], body, ...}` を返す。清書プロンプトは**忠実**（誤字・話し言葉・箇条書き→読みやすい文章に整えるだけ、出来事・気持ちを足さない）。タグは気分/出来事の2〜3個。
- 失敗時は**原文をそのまま body** に、title＝日付、tags＝[] でフォールバック（日記を絶対失わない。`summarize.py`と同じ思想）。
- 依存: Anthropic Messages API（`~/.hermes/.env` の `ANTHROPIC_API_KEY`）。

### `diary_store.py` — 保存・読み出し
- 役割: 日記エントリの永続化と取得。`save(entry)` / `list_entries()` / `get(date)`。
- データ: `data/diary/entries/<YYYY-MM-DD>.json`（1日1ファイル、同日追記はマージ）。写真本体は `data/diary/media/<YYYY-MM-DD>/<n>.jpg`。
- エントリ構造: `{date, title, tags[], body(清書), raw(原文), photos[{file, caption}], created, updated}`。**raw（原文）を必ず残す**＝盛らない担保＋後で再清書可能。
- 依存: ファイルシステムのみ。

### `diary_web.py`（または既存サーバへのルート追加） — 本棚Webページ
- 役割: 日記の一覧・詳細をブラウザ表示。`GET /diary`（一覧）/ `GET /diary/media/...`（写真配信）/ `GET /diary/api/entries`（JSON）。
- 見た目: **テーブルの窮屈さの逆**。1日1枚の広いカード（タイトル・日付・タグ・写真サムネ）、クリックで清書全文＋写真フル表示。player.html / home-hub のトーンを踏襲。
- 配信元: line-news-bot の interactive サーバ（データを所有・既にFunnel公開/cron稼働の実績）。home-hub の本棚に「📔 日記」として登録し、スマホからTailscaleで見返せるようにする。

### `server.py` の webhook 分岐（改修）
- 日記モード中（`diary_state.is_active()`）は、text/image を通常の Hermes ではなく**日記コレクタへ**振り分ける。確定/時間切れで通常に戻る。
- 写真は既存 `line_media.py` で bytes 取得 → `vision.py` で短いキャプション化 → 下書きへ添付（本文には混ぜず、写真の付随情報として保持）。
- 「日記」コマンドで手動開始。text経路・通常Hermes・PDF/画像intakeの既存挙動は日記モード外では不変。

### cron（20時の声かけ）
- 既存の briefing cron と同系。20:00 JST に LINE push「今日どうだった?」＋ `diary_state.start()`。時刻は設定で変更可（デフォルト20:00）。push失敗はログのみ（無反応・クラッシュにしない）。

## データフロー

```
20:00 cron ──push──> LINE「今日どうだった?」＋diary_state.start()
   │
   ▼（ユーザー返信: text / 写真）
server.py webhook ──diary_active?──> diary collector
   │  写真 → line_media.get → vision.read(caption) → append
   │  text → diary_state.classify_reply
   │           ├ more   → append、Hermes「これでいい?」
   │           ├ affirm → diary_compose（清書）→ LINE「こんな日記にしたよ📔 これでいい?」
   │           │             └ affirm → diary_store.save → LINE「保存したよ📔」
   │           └ reject → 収集へ戻る
   └ 02:00 or 無操作 → 自動 compose → 自動 save
```

## エラー処理・安全（既存の流儀を踏襲）

- LINEは**絶対に無反応にしない**（各失敗系で安全な定型文reply）。
- 清書失敗 → **原文で保存**（日記を失わない）。意図判定失敗 → `more`（勝手に確定しない）。
- 下書きはファイル永続化 → サーバ再起動で消えない。時間切れ自動保存で「書いたのに消えた」を防ぐ。
- Hermesにディスク/ファイル権限は与えない。読み取り・保存はすべてline-news-bot側ハンドラ内で完結。
- 普通のHermes（検索/相談/PDF）とは**状態で完全分離**。日記モード外の既存挙動は不変。

## テスト（TDD, pytest, 既存規約）

- `test_diary_state.py`: start/append/classify_reply(モックHaiku: affirm/more/reject)/finalize/timeout/永続化round-trip。
- `test_diary_compose.py`: 清書がinjection可能・失敗時に原文フォールバック・タグ/タイトル生成（モックAPI）。
- `test_diary_store.py`: save/list/get、同日マージ、写真パス、raw保持。
- `test_diary_web.py`: 一覧・詳細ルートのレンダリング、空状態、写真配信。
- `server.py`: 日記モード中の分岐（既存テストの回帰なし）。

## 未決/デフォルト（実装時に確定・必要ならユーザー確認）

- 声かけ時刻: デフォルト 20:00 JST（設定で可変）。
- 時間切れ: 当日 02:00 JST（暫定）。
- タグの語彙: 固定リストにせずHaiku自由生成（気分/出来事、2〜3個）。二重制限を避ける方針に沿う。

## この設計に含めない（YAGNI）

- 日記の全文検索・感情グラフ等の分析機能（まず貯める・見返すに集中）。
- Notionへの同期（軽メモはNotion、重い日記は本ページ、で棲み分け）。
- 音声入力（Mac mini後のSTTスペックで扱う）。
