"""Stage 20 (S20-2): SMTP / Telegram / LLM-ბიუჯეტის Settings."""
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

_EMAIL = {
    "smtp_host": "smtp.example.com",
    "smtp_user": "user",
    "smtp_password": "smtp-secret-pw-123",
    "notify_email_from": "ChatAssist <noreply@chatassist.ge>",
}


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_defaults():
    s = _settings()
    assert s.smtp_port == 587
    assert s.llm_kill_switch is False


def test_channels_disabled_by_default():
    s = _settings()
    assert s.email_notifications_enabled is False
    assert s.telegram_enabled is False


def test_conftest_pins_notify_env_blank():
    assert os.environ["SMTP_PASSWORD"] == ""
    assert os.environ["SMTP_HOST"] == ""
    assert os.environ["TELEGRAM_BOT_TOKEN"] == ""
    assert "SMTP_PORT" not in os.environ


def test_email_enabled_when_all_four_set():
    assert _settings(**_EMAIL).email_notifications_enabled is True


@pytest.mark.parametrize("missing", list(_EMAIL))
@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_email_disabled_when_any_missing(missing, blank):
    s = _settings(**{**_EMAIL, missing: blank})
    assert s.email_notifications_enabled is False


def test_telegram_enabled_needs_both():
    assert _settings(telegram_bot_token="123:abc", telegram_chat_id="-100500").telegram_enabled is True
    assert _settings(telegram_bot_token="123:abc").telegram_enabled is False
    assert _settings(telegram_chat_id="-100500").telegram_enabled is False
    assert _settings(telegram_bot_token="  ", telegram_chat_id="-100500").telegram_enabled is False


def test_string_fields_are_stripped():
    s = _settings(smtp_host=" smtp.example.com\n", telegram_bot_token=" 123:abc\n", telegram_chat_id=" 42 ")
    assert s.smtp_host == "smtp.example.com"
    assert s.telegram_bot_token == "123:abc"
    assert s.telegram_chat_id == "42"


def test_env_values_are_read(monkeypatch):
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("LLM_KILL_SWITCH", "true")
    s = _settings()
    assert s.smtp_port == 465
    assert s.llm_kill_switch is True


@pytest.mark.parametrize("port", [0, -1, 70000, 65536])
def test_smtp_port_out_of_range_rejected(port):
    with pytest.raises(ValidationError):
        _settings(smtp_port=port)


def test_smtp_port_bounds_accepted():
    assert _settings(smtp_port=1).smtp_port == 1
    assert _settings(smtp_port=65535).smtp_port == 65535


def test_repr_hides_secrets():
    s = _settings(**_EMAIL, telegram_bot_token="999:telegram-token-xyz", telegram_chat_id="42")
    text = repr(s)
    assert "smtp-secret-pw-123" not in text
    assert "999:telegram-token-xyz" not in text


def test_token_budget_settings_removed():
    """S21-8 (A-048): the token budget is gone — USD only (see test_config_stage21.py)."""
    s = _settings()
    for name in (
        "llm_daily_token_cap", "llm_daily_tokens_per_owner", "llm_monthly_tokens_free",
        "llm_monthly_tokens_basic", "llm_monthly_tokens_standard", "llm_monthly_tokens_business",
        "llm_monthly_budget",
    ):
        assert not hasattr(s, name), name
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    assert "LLM_DAILY_TOKEN_CAP" not in example
    assert "LLM_DAILY_TOKENS_PER_OWNER" not in example
    assert "LLM_MONTHLY_TOKENS_" not in example
    assert "LLM_DAILY_USD_CAP" in example  # the USD budget stays documented


def test_missing_required_secrets_excludes_new_names():
    missing = " ".join(_settings().missing_required_secrets())
    for name in ("SMTP", "NOTIFY", "TELEGRAM", "LLM_"):
        assert name not in missing
