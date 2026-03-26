import os

from openagent.config.env import load_dotenv


def test_load_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAGENT_PROVIDER=volcengine\nARK_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.delenv("OPENAGENT_PROVIDER", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    load_dotenv(env_file)

    assert os.environ["OPENAGENT_PROVIDER"] == "volcengine"
    assert os.environ["ARK_API_KEY"] == "test-key"
