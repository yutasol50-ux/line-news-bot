"""tmux capture-pane / send-keys の薄いラッパー(テストでモックしやすいよう分離)。"""
import subprocess


def capture(pane: str) -> str:
    try:
        r = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", pane],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout if r.returncode == 0 else ""
    except Exception as e:
        print(f"[ERROR] tmux capture失敗: {e}")
        return ""


def send_key(pane: str, key: str) -> bool:
    try:
        r = subprocess.run(
            ["tmux", "send-keys", "-t", pane, key, "Enter"],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"[ERROR] tmux send-keys失敗: {e}")
        return False
