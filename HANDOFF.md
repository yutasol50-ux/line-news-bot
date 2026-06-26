# LINE News Bot 引き継ぎ情報

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
