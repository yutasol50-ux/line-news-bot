# パーソナライズニュース自動配信システム

## コマンド一覧

```bash
cd /home/yuta/news-delivery-system

# ニュース取得・要約（深夜3時に自動実行）
./venv/bin/python3 news_delivery.py fetch

# 各カテゴリ送信（朝6〜8時に自動実行）
./venv/bin/python3 news_delivery.py send english   # 英語学習 (6時)
./venv/bin/python3 news_delivery.py send economy   # 経済・マーケット (7時)
./venv/bin/python3 news_delivery.py send work      # 仕事・自己啓発 (8時)

# テスト・状態確認
./venv/bin/python3 news_delivery.py test    # 全チャンネルにテスト送信
./venv/bin/python3 news_delivery.py status  # API使用状況確認

# カウンターリセット（緊急時）
./venv/bin/python3 news_delivery.py reset
```

## リクエスト残数確認
```bash
./venv/bin/python3 news_delivery.py status
cat data/request_counter.json
```

## ログ確認
```bash
tail -f logs/news_delivery.log
```

## エラー発生時の対処

| エラー | 原因 | 対処 |
|--------|------|------|
| `GEMMA_API_KEY` エラー | APIキー不正 | `.env`を確認 |
| Discord送信失敗 404 | チャンネルID誤り | `.env`のCHANNEL_*を確認 |
| RSS取得失敗 | フィードURLが変更 | `news_delivery.py`のRSS_SOURCESを更新 |
| API上限到達 | 900回/日超過 | 翌日0時に自動リセット |

## サービス稼働確認
```bash
docker ps  # n8n(5678)とOpen WebUI(8080)の確認
crontab -l  # スケジュール確認
```

## 自動実行スケジュール
- 03:00 JST - ニュース取得・Gemma4要約
- 06:00 JST - 英語学習チャンネルに送信
- 07:00 JST - 経済・マーケットチャンネルに送信
- 08:00 JST - 仕事・自己啓発チャンネルに送信
- 23:55 JST - ステータスログ出力
