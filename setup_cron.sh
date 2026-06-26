#!/bin/bash
# LINE秘書ブリーフィング cron設定
# 実行: bash setup_cron.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/venv/bin/python3"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# 旧ニュース配信cron(news_delivery.py)と旧秘書cronを全て除去してから再設定
TEMP=$(mktemp)
crontab -l 2>/dev/null \
  | grep -v "news_delivery.py" \
  | grep -v "secretary.py" \
  | awk '
      /# ======== パーソナライズニュース自動配信システム/ { skip=1 }
      /# ======== LINE秘書ブリーフィング/ { skip=1 }
      /# ====================================================/ { if(skip){skip=0; next} }
      /# ==================================================/ { if(skip){skip=0; next} }
      !skip { print }
    ' > "$TEMP"

cat >> "$TEMP" << EOF

# ======== LINE秘書ブリーフィング ========
# 朝5:30: カレンダー予定+天気2地点+今朝のニュース+本日の一語 を1通で配信
30 5 * * * cd $SCRIPT_DIR && git pull --quiet 2>/dev/null; $PYTHON $SCRIPT_DIR/secretary.py >> $LOG_DIR/secretary.log 2>&1
# ==================================================
EOF

crontab "$TEMP"
rm "$TEMP"

echo "✅ Cron設定完了"
echo ""
echo "現在のCron設定:"
crontab -l | grep -A 4 "LINE秘書ブリーフィング"
