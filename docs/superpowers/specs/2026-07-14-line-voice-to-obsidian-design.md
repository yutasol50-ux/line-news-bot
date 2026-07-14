# 設計: LINE音声 → Gemini文字起こし → Obsidian ノート化

- 日付: 2026-07-14
- ステータス: 設計（レビュー待ち）
- 関連: `interactive/media_intake.py`（画像/PDF版の先行例）, `~/tool/gemini_transcribe.py`（文字起こしの原型）, 共有Obsidian vault `vault with claude`

## 目的・背景

オーナー（Yuta）が録音した音声（自分の思考メモ、講演・対談の録音。**長さは40分前後〜それ以上、"録音しっぱなし"も想定**）を、**LINEに送るだけ**でObsidian vaultに「読める整形ノート」として残せるようにする。

現状の代替手段（Haiku系STTや手作業）は品質がいまいち。**文字起こしはGeminiが桁違いに正確**なことが実証済み（WebX26のAudrey Tang対談を完全復元）。これを既存のLINE秘書（Hermes）基盤に配管する。

### 品質分担（重要）
- **文字起こし＋下書き整形**: Gemini（自動・無料・Haikuより上）
- **最終清書**: 後日PCで Opus（Claude Code）が `_inbox/` の下書きを仕上げる（＝オーナーが求める"Opus品質"はここで担保）

## スコープ

### やる
- LINEに来た**音声メッセージ/音声ファイル**を取得 → Gemini文字起こし → Gemini下書き整形 → Obsidian `_inbox/` に `.md` 保存 → LINEへ完了通知
- **長尺対応**（ffmpeg分割）と**途中で落ちても消えない durability**（先に保存＋再開）
- **冪等性**（同一音声/LINE webhook再送での二重ノート化を防止）

### やらない（今回）
- 音声で秘書と"雑談"する機能（音声＝すべてObsidian行き）
- テキスト/画像からのObsidianノート化（音声に集中。将来拡張）
- キューの可視化UI・優先度制御
- Opus清書の自動化（清書は手動でPCで行う）

## 全体フロー

```
①LINEに音声を送る
②server.py が mtype=audio を検知 → voice_intake.handle() を非同期起動
③即：音声バイトを pending/<message_id>.<ext> に保存＋message_idを seen に記録
   → LINEへ即レス「受け取った！文字起こしするね（少しかかるよ）」   ← “渡すだけ”完了・消えない
④裏で voice_intake がGemini文字起こし:
   - 短尺: そのまま1回
   - 長尺(20分超): ffmpegで20分ごとに分割 → 各チャンクを文字起こし(503リトライ付) → 連結
⑤Geminiで下書き整形（タイトル / 要点 / 見出し付き本文）
⑥Obsidian vault の _inbox/ に .md 保存（frontmatter status: draft, tag #要清書）
⑦LINEへ「📝『タイトル』ノートにしたよ / 要点3行 / ※後でOpus清書待ち」
⑧pending/<message_id> を削除（完了）

（プロセスが途中で落ちた場合）
   pending/ に音声が残る → 起動時 & 定期チェック(cron)で未完了を1本ずつ拾って再開
```

## コンポーネント

### 既存（流用）
- `interactive/line_media.py` : `fetch_content(message_id)` → (bytes, content_type)。音声もそのまま取得できる。**変更なし**。
- `interactive/server.py` : `mtype not in ("text","image","file")` の分岐で音声を落としている箇所（`# audio 等は未対応(将来STT)`）を、**audio→voice_intake へ**に差し替え。既存の `_spawn(...)` で非同期起動。
- `shared/line_client.py` : `reply()` で受領/完了メッセージ送信。**変更なし**。
- `~/tool/gemini_transcribe.py` : 文字起こしのコア（File API・503リトライ・フォールバック実装済み）。**import 可能な関数に小改造**（`transcribe(path) -> str`）。

### 新規
- `interactive/voice_intake.py` : オーケストレータ（`media_intake.py` と同じ設計思想）。
  - `handle(message_id, reply_token)`: 保存→受領レス→（裏で）処理起動
  - 依存は引数注入（fetch/transcribe/structure/write_note/reply）でテスト可能に
- `interactive/gemini_transcribe.py`（または `shared/`）: `~/tool/` 版を取り込み。`transcribe(path)` と、長尺分割 `transcribe_long(path)` を提供。
- `interactive/obsidian_writer.py` : `write_draft(title, body, meta) -> path`。vaultの `_inbox/` に安全なファイル名で書き込む小関数。パスは env で設定。
- `interactive/voice_drain.py` : `pending/` の未完了を1本ずつ再開する掃除役（起動時＋cron）。
- `data/voice/pending/` : 未処理音声の置き場（durability の要）。
- `data/voice/seen.json` : 処理済み message_id 記録（dedup）。

### 整形プロンプト（Geminiの下書き）
- 出力: 1行目にタイトル、続けて「要点(3〜5個)」＋「見出し付き本文」。誤変換の注記。日本語。
- あくまで**下書き**（後でOpusが清書する前提）。過剰要約しない。

## Obsidian 出力仕様
- 置き場: `<vault>/_inbox/YYYY-MM-DD-<slug>.md`
- frontmatter:
  ```yaml
  ---
  tags: [voicememo, 要清書]
  created: <date>
  source: LINE音声 → Gemini(自動下書き)
  status: draft        # Opus清書後に done へ
  message_id: <LINE message id>
  ---
  ```
- 本文: Geminiの下書き（タイトル→要点→本文）＋末尾に「## 全文（Gemini文字起こし）」で生テキストも保持（清書時の原資料）。
- **Opus清書ワークフロー**: PCで `_inbox/` の `status: draft` を探す → 清書して本編（vault直下や適切なフォルダ）へ → `status: done`。

## エラー処理・信頼性
- **Gemini 503/429**: 指数バックオフ（既存、5回）。それでも不可なら pending に残したまま、LINEへ「今Gemini混雑。あとで自動で再挑戦するね」。次回drainで再試行。
- **クラッシュ/スリープ/深夜再起動で中断**: 音声は pending に残る → 起動時＆cronのdrainが未完了を再開。**作業ロスト無し**。
- **無料枠上限（RPD/TPD）超過**: LINEへ「今日の無料枠に達したかも。大きい録音はGeminiアプリ手動が確実だよ」と正直に通知。設計上の天井であり実装バグではない。
- **二重処理防止**: 先頭で message_id を seen 照合。既知ならスキップ（LINE webhook 再送・オーナーの再送どちらも吸収）。

## 長尺の扱い（技術メモ）
- **出力トークン切れ対策**: 長い音声を1回で投げると文字起こしが尻切れになりうる。`maxOutputTokens` を上限まで引き上げ、かつ**20分超は ffmpeg で20分チャンクに分割**して個別文字起こし→連結。
- **チャンクサイズの balance**: 小さすぎるとリクエスト数が増えてRPDを食う／大きすぎると出力切れ。**~20分**を初期値に、実測で調整。
- 分割は `ffmpeg -i in.m4a -f segment -segment_time 1200 -c copy chunk_%03d.m4a`（無劣化コピー）。

## テスト観点
- 短い音声（数十秒）: 取得→文字起こし→ノート生成→LINEレス（依存注入でモック）
- 長い音声: 分割→各チャンク→連結の順序・欠落なし
- 冪等: 同一message_idの二重投入で1ノートのみ
- 中断再開: pending 残置→drainで完了
- 503: リトライ後に pending 残置＆通知

## 未確定・リスク
- **無料枠の実効上限**（数時間×毎日は無理）。→ 保険＝Geminiアプリ手動、将来＝Mac mini M5でローカルWhisper移行。
- systemd(WSL)サービスから `/mnt/c`（iCloudフォルダ）へ書き込めるかは実装時に要検証。
- 録音しっぱなしの音声は無音/雑音区間が多い可能性。品質は実測で判断（YAGNIで前処理は入れない）。

## 将来拡張（but-later）
- 音声で秘書と雑談（Obsidian行きか会話かをオーナーが指定）
- テキスト/画像→Obsidian（"何でも箱"の完成形）
- Opus清書の半自動化（claude-hermes-bridge 経由）
- Mac mini 到着後、文字起こしをローカルWhisperへ切替（無料枠から解放）
