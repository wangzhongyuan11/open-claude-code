from openagent.config.settings import Settings


def test_settings_defaults_from_workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAGENT_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAGENT_MODEL", raising=False)
    monkeypatch.delenv("OPENAGENT_BASH_TIMEOUT", raising=False)

    settings = Settings.from_workspace(tmp_path)

    assert settings.workspace == tmp_path.resolve()
    assert settings.session_root == tmp_path.resolve() / ".openagent" / "sessions"
    assert settings.log_root == tmp_path.resolve() / ".openagent" / "logs"
    assert settings.bash_timeout_seconds == 30
