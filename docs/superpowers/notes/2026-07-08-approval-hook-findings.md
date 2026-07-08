# スパイク結果: Notification フック発火と pane 特定（Task 1）

実施日: 2026-07-09（実機検証）

## 判断: **フック方式で進む（Task 8 は原案どおり）**。ポーリング常駐フォールバックは不要。

## 検証内容
tmux 内でネストした Claude Code を起動し、Bash 書き込みコマンド（`touch`）で承認プロンプトを発生させ、
一時登録した Notification プローブフック（stdin と env をログするだけ）の発火を観測した。

## 確認できたこと

1. **Notification フックは承認プロンプトで発火する（Yes）。**
2. **stdin JSON で通知種別を判別できる。** 重要フィールド:
   - `hook_event_name`: `"Notification"`
   - `notification_type`: `"permission_prompt"`（承認待ち） / `"idle_prompt"`（ただの入力待ち）
   - `message`: `"Claude needs your permission"` / `"Claude is waiting for your input"`
   - 他に `session_id`, `transcript_path`, `cwd`, `prompt_id`
3. **`TMUX_PANE` は env から取れる**（例 `%1`）。pane 特定OK。
4. **既存 `approval_parse.parse` は実プロンプトを正しく解析**（下記実サンプルで `question` + choices 1/2/3 抽出成功）。regex 修正不要。

## 実サンプル（`scratch/prompt_capture.txt` より、承認プロンプト部）
```
 Bash command

   touch /home/yuta/probe_marker.txt
   Create probe marker file

 Do you want to proceed?
 ❯ 1. Yes
   2. Yes, and always allow access to yuta/ from this project
   3. No

 Esc to cancel · Tab to amend · ctrl+e to explain
```
- マーカー `Do you want to proceed?` は原案の `_PROMPT_MARKERS` に一致。
- 選択肢行は先頭に空白＋`❯`／`数字.` 形式で、`_CHOICE_RE` に一致。
- サンドボックスで安全な読取コマンド（`echo hi` 等）は**プロンプトなしで自動実行**される＝遠隔承認の対象は主に書き込み/ネットワーク系。

## Task 8 への改善提案（原案からの差分）
- フックスクリプトは stdin JSON を読み、`notification_type == "permission_prompt"` の時だけ処理を進める。
  `idle_prompt` では即 exit（入力待ちのたびに 45 秒 sleep プロセスが湧くのを防ぐ）。
- 原案は stdin を読み捨てる設計だったが、この判別を入れる方が無駄がなく安全。
- 注意: サンドボックス自動実行される読取系はそもそもプロンプトが出ない＝遠隔通知も飛ばない（期待どおりの挙動）。

## 副次的な安全確認
- プローブフックは無害（ログのみ）。検証後 `~/.claude/settings.json` から削除済み。
- `touch` はキャンセル（Esc）したのでマーカーファイルは作られていない。`scratch/` は gitignore 済み。
