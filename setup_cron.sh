#!/bin/bash
# クロン設定スクリプト
# 実行: bash setup_cron.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="python3"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

CRON_CMD="$PYTHON $SCRIPT_DIR/news_delivery.py"
LOG_OPT=">> $LOG_DIR/news_delivery.log 2>&1"

# 既存のニュース配信cronを削除してから再設定
TEMP=$(mktemp)
crontab -l 2>/dev/null | grep -v "news_delivery.py" > "$TEMP"

cat >> "$TEMP" << EOF

# ======== パーソナライズニュース自動配信システム ========
# 深夜3時: 全カテゴリのニュース取得・Gemma4で要約
0 3 * * * $CRON_CMD fetch $LOG_OPT

# 朝6時: 英語学習ニュースをDiscordに送信
0 6 * * * $CRON_CMD send english $LOG_OPT

# 朝7時: 経済マーケットニュースをDiscordに送信
0 7 * * * $CRON_CMD send economy $LOG_OPT

# 朝8時: 仕事・自己啓発ニュースをDiscordに送信
0 8 * * * $CRON_CMD send work $LOG_OPT

# 翌日0時: カウンターリセット確認（reset_counterは自動リセットするため確認用）
55 23 * * * $CRON_CMD status $LOG_OPT
# ======================================================
EOF

crontab "$TEMP"
rm "$TEMP"

echo "✅ Cron設定完了"
echo ""
echo "現在のCron設定:"
crontab -l | grep -A 20 "ニュース自動配信"
