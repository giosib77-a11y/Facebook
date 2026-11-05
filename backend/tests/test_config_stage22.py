"""Stage 22 (S22-1): ძებნა დიდ კატალოგზე / JWT ლოკალური შემოწმება — Settings, .env.example, conftest."""
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

_ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def _s(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_stage22_defaults():
    s = _s()
    assert s.bot_db_search_min_products == 300
    assert s.jwt_local_verify is True


def test_bot_db_search_min_products_from_env(monkeypatch):
    monkeypatch.setenv("BOT_DB_SEARCH_MIN_PRODUCTS", "50")
    assert _s().bot_db_search_min_products == 50


def test_bot_db_search_min_products_zero_allowed(monkeypatch):
    monkeypatch.setenv("BOT_DB_SEARCH_MIN_PRODUCTS", "0")
    assert _s().bot_db_search_min_products == 0


def test_bot_db_search_min_products_negative_rejected(monkeypatch):
    monkeypatch.setenv("BOT_DB_SEARCH_MIN_PRODUCTS", "-1")
    with pytest.raises(ValidationError):
        _s()


def test_jwt_local_verify_false_from_env(monkeypatch):
    monkeypatch.setenv("JWT_LOCAL_VERIFY", "false")
    assert _s().jwt_local_verify is False


def test_env_example_documents_stage22_settings():
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "BOT_DB_SEARCH_MIN_PRODUCTS=300" in text
    assert "JWT_LOCAL_VERIFY=true" in text


def test_conftest_unpins_stage22_env():
    assert "BOT_DB_SEARCH_MIN_PRODUCTS" not in os.environ
    assert "JWT_LOCAL_VERIFY" not in os.environ
