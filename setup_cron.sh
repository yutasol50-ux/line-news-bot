#!/bin/bash
# クロン設定スクリプト
# 実行: bash setup_cron.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/venv/bin/python3"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

CRON_CMD="$PYTHON $SCRIPT_DIR/news_delivery.py"
LOG_OPT=">> $LOG_DIR/news_delivery.log 2>&1"

# 既存のニュース配信cronを削除してから再設定（セクション全体を削除）
TEMP=$(mktemp)
crontab -l 2>/dev/null | awk '
  /# ======== パーソナライズニュース自動配信システム/ { skip=1 }
  /# ====================================================/ { if(skip) { skip=0; next } }
  !skip { print }
' | grep -v "news_delivery.py" > "$TEMP"

cat >> "$TEMP" << EOF

# ======== パーソナライズニュース自動配信システム ========
# 深夜3時: 全ソースからニュース取得・Cohereで要約＋ラベル付け
0 3 * * * cd $SCRIPT_DIR && git pull --quiet && $CRON_CMD fetch $LOG_OPT

# 朝7時: スコア順で厳選してLINEに送信（3〜6通）
0 7 * * * $CRON_CMD send $LOG_OPT

# 深夜23:55: ステータスログ
55 23 * * * $CRON_CMD status $LOG_OPT
# ======================================================
EOF

crontab "$TEMP"
rm "$TEMP"

echo "✅ Cron設定完了"
echo ""
echo "現在のCron設定:"
crontab -l | grep -A 20 "ニュース自動配信"
