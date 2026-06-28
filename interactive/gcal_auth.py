#!/usr/bin/env python3
"""一度だけ実行してGoogleカレンダー書き込みを承認し、トークンを保存する。
WSLではブラウザが自動で開けないので、表示されるURLをWindows側ブラウザで開いて承認する。"""
import os
from pathlib import Path
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

_BASE = Path(__file__).resolve().parent.parent
load_dotenv(_BASE / ".env")
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CLIENT = _BASE / os.environ.get("GCAL_CLIENT_SECRET_PATH", "secrets/gcal_client.json")
TOKEN = _BASE / os.environ.get("GCAL_TOKEN_PATH", "secrets/gcal_token.json")

if __name__ == "__main__":
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
    # WSL: ローカルサーバー方式。表示URLをWindows側ブラウザで開いて承認する。
    creds = flow.run_local_server(port=0, open_browser=False)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    print(f"✅ 認証完了。トークンを保存: {TOKEN}")
