import pytest
from pydantic import ValidationError

from app.config import Settings


def test_app_env_defaults_to_production(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    s = Settings(_env_file=None)
    assert s.app_env == "production"
    assert s.is_production is True


def test_app_env_development_is_not_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    assert Settings(_env_file=None).is_production is False


# A-019: only an explicit allowlist turns production protections off.
@pytest.mark.parametrize("value", ["development", "dev", "test", " Dev ", "TEST"])
def test_app_env_explicit_non_production_values(monkeypatch, value):
    monkeypatch.setenv("APP_ENV", value)
    assert Settings(_env_file=None).is_production is False


@pytest.mark.parametrize("value", ["production", "prod", " PRODUCTION ", ""])
def test_app_env_production_values(monkeypatch, value):
    monkeypatch.setenv("APP_ENV", value)
    s = Settings(_env_file=None)
    assert s.is_production is True and s.app_env == "production"


@pytest.mark.parametrize("value", ["prd", "live", "staging", "develop", "production2", "local"])
def test_app_env_unknown_value_refuses_to_start(monkeypatch, value):
    monkeypatch.setenv("APP_ENV", value)
    with pytest.raises(ValidationError, match="APP_ENV"):
        Settings(_env_file=None)
