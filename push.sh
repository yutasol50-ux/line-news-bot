#!/bin/bash
# 使い方: bash push.sh ghp_xxxxxxxx
TOKEN=$1
if [ -z "$TOKEN" ]; then
  echo "使い方: bash push.sh ghp_xxxxxxxx"
  exit 1
fi

cd /home/yuta/line-news-bot
git remote set-url origin "https://yutasol50-ux:${TOKEN}@github.com/yutasol50-ux/line-news-bot.git"
git push --set-upstream origin main
echo "完了"

cd /home/yuta/line-bot
git remote set-url origin "https://yutasol50-ux:${TOKEN}@github.com/yutasol50-ux/line-bot.git"
git add app.py
git commit -m "Add feedback handler"
git push
echo "line-bot 完了"
