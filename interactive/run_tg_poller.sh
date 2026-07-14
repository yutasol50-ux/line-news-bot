#!/usr/bin/env bash
set -euo pipefail
cd /home/yuta/line/line-news-bot
exec venv/bin/python interactive/telegram_approval_poller.py
