from litrex.config import Settings


def test_settings_defaults_without_env(monkeypatch):
    monkeypatch.delenv("LITREX_ANTHROPIC_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.anthropic_api_key is None
    assert s.anthropic_model == "claude-sonnet-5"
