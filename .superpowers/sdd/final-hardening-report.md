# 最終ハードニング報告(feat/line-voice-to-obsidian)

READY-WITH-MINORS レビューで挙がった Important 4件を修正。TDD(テスト追加→実装)で対応し、
公開関数シグネチャ(`handle`, `process`, `claim`, `transcribe`, `transcribe_long`, `draft_note`,
`write_draft`)は変更していない。

## Finding 1(security) — GEMINI_API_KEY のログ漏洩

**変更箇所**: `interactive/gemini_transcribe.py`
- `_safe_request_error()` を追加(L46-49): `requests.exceptions.RequestException` を
  `RuntimeError(f"Gemini request failed: {type(e).__name__}")` に変換し、URL/`?key=`を含めない。
- `_upload_file()`(L68-110): アップロード開始POST・アップロード本体POST・ファイル状態ポーリングGET
  の3箇所を `try/except requests.exceptions.RequestException` で包み、`raise _safe_request_error(e) from None`。
- `_generate_with_retry()`(L129-143): `generateContent` の POST を try/except で包み、接続エラーを
  429/500/503 と同じ扱い(`last_error`に安全な文字列を記録し、指数バックオフで `sleep()` してリトライ)にした。
  両モデル・全リトライを使い切っても失敗する場合は、従来通り `last_error` を含む安全な `RuntimeError` で諦める。

**ロックしたテスト**: `tests/test_gemini_transcribe.py`
- `test_transcribe_connection_error_does_not_leak_api_key` — `post` が
  `requests.exceptions.ConnectionError(f"...{url}...")`(URLに`key=SECRET`を含む)を投げても、
  `transcribe()` が送出する `RuntimeError` の文字列に `"SECRET"` も `"key="` も含まれないことを確認。
- `test_transcribe_retries_after_connection_error_then_succeeds` — 1回目に接続エラー、2回目で成功する
  `post` を注入し、即失敗せずリトライして成功することを確認(一過性ネットワーク不調はリトライが必要という要件)。

**pytest出力**:
```
tests/test_gemini_transcribe.py::test_transcribe_connection_error_does_not_leak_api_key PASSED
tests/test_gemini_transcribe.py::test_transcribe_retries_after_connection_error_then_succeeds PASSED
```
(既存9件も含め `tests/test_gemini_transcribe.py` 11件全PASS)

---

## Finding 2 + 5 — seen.json の非原子的書き込み & 無制限肥大化

**変更箇所**: `interactive/voice_intake.py`
- `_atomic_write_json(path, obj)`(L37-51新設): 同一ディレクトリに `tempfile.mkstemp` で一時ファイルを作り
  `json.dump` → `os.replace(tmp, path)` で原子的に差し替え。失敗時はtmpを掃除して例外を再送出。
  kill/クラッシュで `seen.json` が途中まで書かれた状態で残ることがなくなった(既存ファイルは無傷のまま)。
- `_load_seen_ids()` / `_save_seen_ids()`(L53-77): 内部表現を `set` から挿入順を保持する `list` に変更。
  `_save_seen_ids` は `_MAX_SEEN(=2000)` を超えたら **古い方から** 切り詰める(`ids[-_MAX_SEEN:]`)。
  `server.py` の `_MAX_SEEN` 規約(直近2000件)に合わせた。
- `mark_seen` / `claim` / `unmark_seen`(L79-104)は内部で `_load_seen_ids`/`_save_seen_ids` を使うよう更新。
  公開シグネチャ・挙動(戻り値/冪等性)は不変。
- 壊れた/存在しない `seen.json` は `_load_seen_ids` が空リストを返す(既存の「クラッシュしない」挙動を維持)。

**ロックしたテスト**: `tests/test_voice_intake.py`
- `test_save_seen_is_atomic_partial_write_does_not_corrupt` — `os.replace` を失敗させても、
  直前に書かれていた正しい `seen.json` の中身が変わらないことを確認(原子性の直接証明)。
- `test_seen_bounded_and_evicts_oldest_on_overflow` — `_MAX_SEEN`件を直接仕込んだ上で `mark_seen` を
  1回追加(=2001件目)し、永続化された件数が2000件のまま、最古(`id0`)が追い出され最新(`idNEW`)が
  残ることを確認。
- `test_corrupted_seen_json_loads_as_empty_and_does_not_crash` — 壊れたJSONでも `is_seen` が
  クラッシュせず `False`、`claim` が新規に成功することを確認(既存挙動の維持)。

**pytest出力**:
```
tests/test_voice_intake.py::test_save_seen_is_atomic_partial_write_does_not_corrupt PASSED
tests/test_voice_intake.py::test_seen_bounded_and_evicts_oldest_on_overflow PASSED
tests/test_voice_intake.py::test_corrupted_seen_json_loads_as_empty_and_does_not_crash PASSED
```

---

## Finding 4 — リトライ上限なし/デッドレターなし(_BUSYスパム・クォータ浪費)

**変更箇所**: `interactive/voice_intake.py`
- `FAILED_DIR`(L14) / `ATTEMPTS_PATH`(L16) / `MAX_ATTEMPTS = 5`(L24) / `_FAILED` メッセージ(L22)を追加。
- `_load_attempts` / `_incr_attempts` / `_clear_attempts`(L106-127): `data/voice/attempts.json` を
  `_atomic_write_json` で読み書きする、message_id→失敗回数のカウンタ。
- `_quarantine(path)`(L129-133): `os.replace` でpendingファイルを `data/voice/failed/` へ原子的に移動。
- `process()` の失敗パス(L182-197): 失敗のたびに `_incr_attempts` し、`MAX_ATTEMPTS` に達したら
  `_quarantine` → `_clear_attempts` → 最終メッセージ `_FAILED` を1回だけ `push` → `"failed"` を返す。
  上限未満なら従来通り `_BUSY` を `push` して `pending/` に残す(`"retry_later"`)。
  成功時は `_clear_attempts` で過去の失敗カウントを片付ける(L200)。
- `write_draft` 成功〜`os.remove(path)` の間のクラッシュで重複ノートが起こりうる件について、
  `process()` 内に `# known limitation:` コメントを追加(L201-203)。v1では未対応(意図的)。
- `interactive/voice_drain.py` は無変更。`drain()` は元々 `voice_intake.PENDING_DIR` のみを列挙する
  実装であり、`FAILED_DIR` は別ディレクトリなので自然に対象外になる(テストで確認)。

**ロックしたテスト**: `tests/test_voice_intake.py` / `tests/test_voice_drain.py`
- `test_process_quarantines_after_max_attempts` — `MAX_ATTEMPTS-1`回は`"retry_later"`+pending保持を確認した後、
  `MAX_ATTEMPTS`回目で `"failed"`、pendingから消滅、`FAILED_DIR`に同名ファイルが現れる、
  `_BUSY`が`MAX_ATTEMPTS-1`回・`_FAILED`が1回だけpushされることを確認。
- `test_process_below_attempt_cap_stays_pending_and_pushes_busy` — 上限未満では隔離されず、
  `_BUSY`のみが積まれることを確認(既存挙動の維持)。
- `test_process_success_after_prior_failures_clears_attempt_count` — 失敗後に成功したら
  `attempts.json`のカウントが消えることを確認。
- `test_drain_ignores_failed_dir`(`tests/test_voice_drain.py`) — `PENDING_DIR`と`FAILED_DIR`双方に
  ファイルを置き、`drain()`が`PENDING_DIR`のものだけを処理することを確認。

**pytest出力**:
```
tests/test_voice_intake.py::test_process_quarantines_after_max_attempts PASSED
tests/test_voice_intake.py::test_process_below_attempt_cap_stays_pending_and_pushes_busy PASSED
tests/test_voice_intake.py::test_process_success_after_prior_failures_clears_attempt_count PASSED
tests/test_voice_drain.py::test_drain_ignores_failed_dir PASSED
```

---

## 検証コマンドと結果

```
$ venv/bin/python -m pytest tests/test_voice_intake.py tests/test_voice_drain.py tests/test_gemini_transcribe.py -v
...
27 passed in 0.57s

$ venv/bin/python -m pytest tests/ -q
...
246 passed in 4.37s
```

新規/既存テストとも全PASS。回帰なし。

## 変更ファイル一覧(コミット対象)

- `interactive/gemini_transcribe.py`(Finding 1)
- `interactive/voice_intake.py`(Finding 2, 4, 5)
- `tests/test_gemini_transcribe.py`
- `tests/test_voice_intake.py`
- `tests/test_voice_drain.py`
- `data/voice/failed/.gitkeep`(新規、`data/voice/pending/.gitkeep`と同じくgitignore対象を force-add。
  隔離ディレクトリが新規checkoutでも存在するようにするため)

`briefing/daily_word.py` は今回の作業対象外のため未ステージ(作業ツリーに変更が残っているが無視)。

## 既知の限度・懸念

- `write_draft` 成功後〜`os.remove(pending)` 前のクラッシュで重複ノートが生まれうる件は、
  指示通り今回は対応せず、コード内コメントのみ残した(v1で許容)。
- `attempts.json` / `failed/` のファイルは message_id ベースの拡張子付きファイル名で識別しており、
  `pending/` と同じ命名規則(`{message_id}.{ext}`)に依存している。命名規則が将来変わる場合は
  `_find_pending` / `_quarantine` も合わせて見直しが必要。
- `seen.json` の2000件上限による「非常に古いmessage_idの再受理」はLINEの再送ウィンドウを大きく超えるため
  実運用上のリスクは低いと判断(指示に明記の通り許容)。

---

## 追補: Opus再レビュー分(Important 1件 + Minor 1件)

前回ラウンドで `_generate_with_retry` の接続エラーは塞いだが、File API アップロード経路
(`_upload_file`)の `raise_for_status()` 呼び出し自体が try/except の**外**にあり、
403/400等でURL(`?key=SECRET`)入りの `HTTPError` がそのまま `voice_intake.process` の
`except ... print(...)` → journalctl まで抜けるルートが残っていた(Important再指摘)。
また `_quarantine` の `os.replace` が無防備で、並行drain/processでpendingが既に消えていると
`FileNotFoundError` が `process()` の except節から漏れ、`_clear_attempts`/`push(_FAILED)` が
実行されず `attempts.json` にゴミが残る問題(Minor)も指摘された。

### Important — File API アップロード経路の `raise_for_status()` キー漏洩

**変更箇所**: `interactive/gemini_transcribe.py`
- `_check_status(resp, what)` を追加(`_safe_request_error`のすぐ下): `resp.status_code >= 400` なら
  `resp.text`もURLも含めず `RuntimeError(f"Gemini {what} failed: HTTP {resp.status_code}")` を送出。
- `_upload_file()` 内の3箇所を置き換え:
  - アップロード開始POST(`start`) → `start.raise_for_status()` を `_check_status(start, "upload開始")` に。
  - アップロード本体POST(`up`) → `up.raise_for_status()` を `_check_status(up, "upload送信")` に。
  - ファイル状態ポーリングGET → 元々 `raise_for_status()` は呼ばれていなかったが、防御的に
    `_check_status(poll, "処理状態確認")` を追加(将来403を返すサーバ実装が来ても同じ経路で安全になるよう)。
- resumableアップロードの正常系(200固定・`X-Goog-Upload-URL`ヘッダ・`ACTIVE`状態)は無変更(既存テスト
  `test_transcribe_uses_file_api_for_large_files` がPASSし続けることで確認)。

**ロックしたテスト**: `tests/test_gemini_transcribe.py`
- `_Resp403`(罠付きフェイクレスポンス): `raise_for_status()` を呼べば実際に
  `HTTPError(f"... for url: {self.url}")`(=`?key=SECRETKEY`込み)を投げるよう作ってあり、
  「実装が `raise_for_status()` を呼んでいない」ことをテストの裏返しとして保証する。
- `test_upload_start_403_does_not_leak_api_key` — File API経由(8MB=inline閾値超え)で
  アップロード開始が403 → `transcribe()` が送出する `RuntimeError` に `"SECRETKEY"` も `"key="` も無い。
- `test_upload_send_403_does_not_leak_api_key` — アップロード本体送信(`up`)が403でも同様。
- `test_upload_file_directly_403_does_not_leak_key` — `_upload_file()` を直接呼び、start段階403でも漏れない。
- `test_upload_file_poll_403_does_not_leak_key` — ファイル状態ポーリング(`get`)が403でも漏れない
  (`_check_status`を防御的に追加した効果の確認)。

**pytest出力**:
```
tests/test_gemini_transcribe.py::test_upload_start_403_does_not_leak_api_key PASSED
tests/test_gemini_transcribe.py::test_upload_send_403_does_not_leak_api_key PASSED
tests/test_gemini_transcribe.py::test_upload_file_directly_403_does_not_leak_key PASSED
tests/test_gemini_transcribe.py::test_upload_file_poll_403_does_not_leak_key PASSED
```

### Minor — `_quarantine` の `FileNotFoundError` 無防備

**変更箇所**: `interactive/voice_intake.py`
- `_quarantine(path)`: `os.replace(path, dest)` を `try/except FileNotFoundError: pass` で包んだ。
  移動元が既に無い(並行drain/processで消えていた)場合は隔離が目的達成済みとみなし、例外を出さずに
  `dest` を返す。無関係な例外(権限エラー等)はそのまま伝播する。
- 呼び出し側 `process()` は変更なし: `_quarantine` が例外を出さなくなったことで、直後の
  `_clear_attempts(message_id)` と `push(_FAILED)` が必ず実行されるようになった
  (以前は `FileNotFoundError` が `process()` のexcept節の外(=quarantine呼び出しの内側)から
  伝播し、`_clear_attempts`/`push`がスキップされて `attempts.json` にゴミが残っていた)。

**ロックしたテスト**: `tests/test_voice_intake.py`
- `test_quarantine_tolerates_already_missing_source` — 最初から存在しないパスを`_quarantine`に渡しても
  例外を出さないことを直接確認。
- `test_process_quarantine_survives_concurrent_removal_and_clears_attempts` — `MAX_ATTEMPTS-1`回失敗させた後、
  `os.replace`を「quarantine対象のpendingファイルの移動だけ」`FileNotFoundError`にすり替えて並行削除を再現
  (`_atomic_write_json`が使う`os.replace`は元の実装にフォールバックさせ、他のI/Oを壊さないようにした)。
  `MAX_ATTEMPTS`回目で`process()`が例外を出さず`"failed"`を返し、`attempts.json`から該当エントリが
  消え、`_FAILED`が1回だけpushされることを確認。

**pytest出力**:
```
tests/test_voice_intake.py::test_quarantine_tolerates_already_missing_source PASSED
tests/test_voice_intake.py::test_process_quarantine_survives_concurrent_removal_and_clears_attempts PASSED
```

### 検証コマンドと結果(追補分)

```
$ venv/bin/python -m pytest tests/test_gemini_transcribe.py tests/test_voice_intake.py -v
...
31 passed in 0.94s

$ venv/bin/python -m pytest tests/ -q
...
252 passed in 4.96s
```

新規/既存テストとも全PASS。回帰なし。`briefing/daily_word.py`は今回も作業対象外のため未ステージ。

---

## E2E追補 — `draft_note` タイトルへの前置き混入(実機バグ)

実際のGemini APIに対する生E2Eテストで発覚。`draft_note(transcript)` は出力1行目をそのまま
タイトルとして採用していたが、実機の応答が「以下は音声の文字起こしです。」という会話的な前置き行を
1行目に出してきたため、タイトルが文字通り `"以下は音声の文字起こしです。"` になってしまい、
Obsidianノートの見出し(H1)とファイル名スラッグの両方がこのゴミ文字列で汚染される不具合。

**変更箇所**: `interactive/gemini_transcribe.py`
- `DRAFT_PROMPT`: 出力形式を厳密化。1行目を `TITLE: <タイトル>` から必ず始めさせ、2行目を空行、
  3行目以降を本文とする構造を明示指示。前置き・挨拶・「以下は〜です。」のような説明文を一切付けない
  こと、タイトルに「文字起こし」「音声」などの語を使わないことを明示的に禁止。
- `_parse_title_and_body(text)`(新設): モデル出力からタイトル/本文を頑健に取り出す。
  1. `TITLE:` マーカーが1行目にあれば、そこからタイトルを抽出し、続く空行を飛ばして残りを本文とする。
  2. マーカーが無い場合は旧来通り1行目をタイトルとするが、`_looks_like_preamble()` で
     「文字起こし」を含む行、または「以下は」/「これは」で始まり「です。」で終わる行を前置きとして検出し、
     読み飛ばして次の非空行をタイトルに採用する(モデルがマーカー指示を無視してもタイトルが汚染されない)。
  3. ガード: タイトルが空、または60字を超えて異常に長い場合は、`obsidian_writer._slug()` の40字上限に
     収まるよう先頭40字に切り詰める(空の場合は本文側の最初の非空行から補う)。
- `draft_note()`: パース処理を `_parse_title_and_body()` に委譲。既存のリトライ/バックオフ・
  `maxOutputTokens` の挙動は変更なし。

**ロックしたテスト**: `tests/test_gemini_transcribe.py`
- `test_draft_note_extracts_title_from_marker` — `TITLE: JPYCとステーブルコインの未来\n\n## 要点\n- a\n`
  という出力から `title == "JPYCとステーブルコインの未来"` を取り出し、本文に `TITLE:` 行が残らないことを確認。
- `test_draft_note_drops_preamble_when_no_marker` — マーカー無しで「以下は音声の文字起こしです。」が
  1行目に来る実機再現ケースで、タイトルがその前置き文字列に**ならない**ことを確認(実際に観測したバグの再現テスト)。
- `test_draft_note_truncates_overlong_title` — `TITLE:` の値が100字ある場合、タイトルが40字以下に
  切り詰められることを確認(ファイル名スラッグの40字上限との整合)。
- 既存2件(`test_draft_note_splits_title_and_body` / `test_draft_note_retries_on_503`)は変更なしでPASSを維持。

**pytest出力**:
```
$ venv/bin/python -m pytest tests/test_gemini_transcribe.py -v
...
18 passed in 1.21s

$ venv/bin/python -m pytest tests/ -q
...
255 passed in 5.03s
```

新規/既存テストとも全PASS。回帰なし。`briefing/daily_word.py`は今回も作業対象外のため未ステージ。
