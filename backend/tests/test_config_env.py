from app.config import Settings


def test_app_env_defaults_to_production(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    s = Settings(_env_file=None)
    assert s.app_env == "production"
    assert s.is_production is True


def test_app_env_development_is_not_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    assert Settings(_env_file=None).is_production is False
