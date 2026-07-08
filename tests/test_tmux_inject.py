from unittest.mock import patch, MagicMock
from interactive import tmux_inject


def test_capture_returns_stdout():
    m = MagicMock(); m.returncode = 0; m.stdout = "PANE TEXT"
    with patch("interactive.tmux_inject.subprocess.run", return_value=m) as run:
        out = tmux_inject.capture("%3")
    assert out == "PANE TEXT"
    args = run.call_args[0][0]
    assert args[:3] == ["tmux", "capture-pane", "-p"]
    assert "%3" in args


def test_send_key_calls_send_keys_with_enter():
    m = MagicMock(); m.returncode = 0
    with patch("interactive.tmux_inject.subprocess.run", return_value=m) as run:
        ok = tmux_inject.send_key("%3", "1")
    assert ok is True
    args = run.call_args[0][0]
    assert args[:2] == ["tmux", "send-keys"]
    assert "%3" in args and "1" in args and "Enter" in args


def test_capture_returns_empty_on_failure():
    m = MagicMock(); m.returncode = 1; m.stdout = ""
    with patch("interactive.tmux_inject.subprocess.run", return_value=m):
        assert tmux_inject.capture("%3") == ""
