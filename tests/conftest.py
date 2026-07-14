import pytest


@pytest.fixture(autouse=True)
def _default_gemini_brain(monkeypatch):
    """テストは実環境の .env の HERMES_BRAIN に依存しない。

    server.py が import 時に load_dotenv で .env を読むため、開発機の .env が
    HERMES_BRAIN=on だと既存の dispatch(Gemini)経路テストが Hermes 経路に流れて
    落ちる。ここで既定を off に固定して決定的にする。Hermes 経路を試すテストは
    各自 monkeypatch.setenv("HERMES_BRAIN", "on") で上書きする。
    """
    monkeypatch.delenv("HERMES_BRAIN", raising=False)


@pytest.fixture(autouse=True)
def _default_gemini_api_key(monkeypatch):
    """テストは実環境の .env の GEMINI_API_KEY に依存しない。

    gemini_transcribe.py のテストは _api_key() が環境変数をチェックするため、
    開発機の .env が GEMINI_API_KEY を設定していると、テスト環境では決定的でない。
    ここで既定値 "test-key" に固定して、ダミーキーでテストが動くようにする。
    GEMINI_API_KEY が未設定の場合をテストするテストは各自
    monkeypatch.delenv("GEMINI_API_KEY", raising=False) で削除する。
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
