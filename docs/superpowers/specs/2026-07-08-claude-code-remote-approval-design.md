# Claude Code 遠隔承認 (Watch/iPhoneからyes) 設計

作成: 2026-07-08
ステータス: 設計合意済み → 実装計画へ

## 背景・目的

コーディング/調査中に Claude Code が出す承認プロンプト（`Bash(...)` を実行していいか、
編集していいか等の y/n・番号選択）を、席を離れていても **iPhone / Apple Watch の LINE から
遠隔で答えたい**。席で承認待ちに縛られて進まない問題を解消する。

関連構想メモ: `project_watch_claude_approve` / 既存の Watch→`/capture` 配線・LINE push・
secretary-webhook を流用する。

## 前提となった決定（ブレスト結果）

- **通知/返信チャネル**: LINE 流用 ＋ **クイックリプライボタン**。
  - iPhone・Apple Watch・iPad・PC の LINE、どれでも答えられる。番号選択は iPhone、単純 y/n は Watch が快適。
- **安全の線引き**: **全信頼・一段**。破壊系(rm/push/deploy/restart 等)も含め、何でもワンタップ承認可。
  質問文を本人が読んで判断する前提。破壊系ガード・分類ロジックは作らない。
- **飛ばす契機**: **席を離れた時だけ**。プロンプトがキーボードで N 秒無応答なら初めて LINE へ。
  席にいる時は普段どおり TUI で答えるだけ（LINE は鳴らない）。
- **注入方式**: **tmux + `send-keys`**。普段の TUI 承認画面はそのまま残し、その上に
  「離席時だけ答えを注入する経路」を乗せる。PreToolUse フックで全横取りする方式は取らない
  （キーボード優先が作りにくいため）。

## アーキテクチャ

```
[Yoga: Claude Code は tmux 内で常駐]
        │ ①承認プロンプト発生
        ▼
 Notificationフック ──②N秒キーボード無応答を監視──▶ まだ pane が待機中?
        │ yes                                         │ no(=席で答えた)→何もしない
        ▼
 approval-bridge
   ・質問文 + tmux pane-id を「保留箱」に登録
   ・LINE push（質問文 ＋ クイックリプライ [1.Yes][2.常に許可][3.却下]…）
        │
        ▼
 [iPhone / Apple Watch] LINE通知 → ボタンをタップ
        │ ③postback
        ▼
 secretary-webhook（既存）に「承認」分岐を追加
   ・本人 userId 検証
   ・保留箱から対象 pane を引く
   ・注入前に pane を再キャプチャし「まだ承認待ちか」検証
   ・tmux send-keys -t <pane> "<key>" Enter
        │
        ▼
 [Yoga: Claude Code] 承認が注入され続行
```

**必須前提**: Claude Code が **tmux セッション内**で動いていること（外部から `send-keys` で
答えを注入するため）。透過ラッパー `cc` で普段の打ち方は変えずに tmux 内起動にする。

## コンポーネント

| 部品 | 役割 | 新規/流用 | 置き場所(想定) |
|---|---|---|---|
| `cc` ラッパー | 打つと常駐 tmux セッション内で Claude Code 起動。打ち方は不変 | 新規 | `~/.local/bin/cc` |
| Notification フック | 承認プロンプトで発火。N 秒待って **まだ pane 待機中なら** bridge へ通知 | 新規 | `~/.claude/settings.json` の `hooks.Notification` + スクリプト |
| approval-bridge | 保留箱登録 ＋ LINE push（質問文＋クイックリプライ） | 既存 webhook サーバに間借り | `interactive/approval_bridge.py` |
| 承認ハンドラ | LINE タップ返信を受け→保留箱照合→検証→`send-keys` 注入 | 既存 webhook に分岐追加 | `interactive/server.py` |
| pane 解析 | `tmux capture-pane` の TUI テキストから選択肢/キーを抽出 | 新規 | `interactive/approval_parse.py` |
| 保留箱 | 待機中承認を pane 単位で保持 | 新規 | `data/approvals/pending.json` |

## データ・「何番か」の対応

**一切分類しない。** `tmux capture-pane -p -t <pane>` で TUI の選択肢をそのまま読む:

```
Do you want to proceed?
❯ 1. Yes
  2. Yes, and don't ask again
  3. No, and tell Claude what to do differently
```

→ 見えている選択肢を **そのままクイックリプライのボタンに変換**（`1.Yes` `2.常に許可` `3.却下`）。
各ボタンの postback に「送るキー(`1`/`2`/`3`)」を仕込む。返信が来たら該当キー＋Enter を `send-keys` で撃つ。

保留箱 1 件:

```json
{
  "token": "a1b2",
  "pane": "%3",
  "cwd": "~/line/line-news-bot",
  "question": "Bash(git push ...) を実行していい?",
  "choices": [
    {"key": "1", "label": "Yes"},
    {"key": "2", "label": "常に許可"},
    {"key": "3", "label": "却下"}
  ],
  "created": "2026-07-08T12:00:00+09:00",
  "state": "pending"
}
```

`cwd` を入れることで、複数セッション時も「どのプロジェクトの承認か」が腕で分かる。

## タイムアウト・多重・安全

- **離席しきい値 N**: デフォルト 45 秒（設定可）。フックが発火後 N 秒待ち、pane を再キャプチャして
  承認プロンプトがまだ残っていれば push、消えていれば（席で答えた）何もしない。
- **空振り防止（重要）**: LINE 返信が来た瞬間に **pane を再キャプチャし「まだ承認待ちか」を検証**。
  席で先に答えた/別作業に移っていたら **注入せず**「もう解決済みでした」と返す。
  稼働中セッションへ迷子の `y` を撃ち込む事故を防ぐ。
- **多重セッション**: 保留箱は pane 単位。同時に 2 件待てば push 本文に `cwd` を出して区別。
  MVP は小さなキューで正しく動く。
- **本人限定**: webhook は既に LINE 署名検証済み。さらに **本人 userId のみ承認可**にフィルタ。
- **フォールバック**: LINE push が失敗しても何も壊れない（キーボードの TUI 承認はそのまま待機）。

## テスト方針

- **単体**
  - pane 解析: 実 TUI サンプル（y/n 形・番号形・don't-ask 形など）→ 期待ボタン/キーの表テスト。
  - クイックリプライ生成: choices → LINE quick-reply メッセージ構造。
  - 承認ハンドラ: tmux をモックし `send-keys` 引数を検証。**「非待機なら注入しない」**を検証。
  - 本人 userId 以外は無視することを検証。
- **手動 E2E**: 実 tmux で承認プロンプト発生 → LINE push → タップ → 注入 の一気通し。

## 実装前に要検証（設計の前提リスク）

- **Notification フックが承認プロンプトで発火するか**: Claude Code の `Notification` フックが
  「権限プロンプト表示時」に発火し、そこから pane を特定できることが本設計の土台。
  もし承認時に発火しない/情報が足りない場合は、代替として **pane を定期 `capture-pane` で
  ポーリングして承認プロンプト出現を検知する常駐ウォッチャ**に切替える（アーキ全体は不変、
  検知トリガのみ差し替え）。実装 Task 1 で最初に裏取りする。
- **`send-keys` の TUI 互換**: Claude Code の TUI に対し `send-keys "1" Enter` で選択肢確定が
  効くこと（IME/装飾入力の干渉が無いこと）を実機で確認。

## スコープ外（YAGNI / 将来）

- 破壊系の分類・二段ガード（今回は全信頼・一段で不要）。
- Watch 専用ショートカット（LINE で iPhone/Watch 両対応できるため不要）。
- 自由記述の返信（「3.却下」時に Claude へ指示を書く等）は将来拡張。MVP は選択肢キー送信のみ。
- 席にいる時の任意 push（今回は離席フォールバックのみ）。
```

