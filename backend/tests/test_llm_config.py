"""S14-2: LLM provider settings, llm_ready, startup warning (no network, no real keys)."""
import logging

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings
from app.main import check_required_settings, warn_if_llm_disabled

KEY_VALUE = "SENTINEL-LLM-KEY-VALUE"


def _s(**kw) -> Settings:
    # conftest pins a dummy ANTHROPIC_API_KEY in the env; init kwargs win over env, so blank
    # keys must be explicit unless the test passes its own
    kw.setdefault("anthropic_api_key", "")
    kw.setdefault("openai_api_key", "")
    return Settings(_env_file=None, **kw)


def _prod_kwargs(**over) -> dict:
    vals = dict(
        app_env="production", supabase_url="https://x.supabase.co",
        supabase_publishable_key="pk", supabase_secret_key="sk", fb_app_secret="s",
        fb_verify_token="v", fb_token_encryption_key=Fernet.generate_key().decode(),
        client_ip_trusted_hops=3,
    )
    vals.update(over)
    return vals


def _prod_without_llm_key() -> Settings:
    return _s(**_prod_kwargs())


def test_defaults(monkeypatch):
    # conftest pins a dummy anthropic key + provider; remove them to see the class defaults
    for name in ("LLM_PROVIDER", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name)
    s = _s()
    assert s.llm_provider == "claude"
    assert s.anthropic_api_key == "" and s.openai_api_key == ""
    assert s.claude_model == "claude-haiku-5-5"
    assert s.openai_model == "gpt-6-luna"
    assert s.llm_timeout_seconds == 20.0
    assert s.llm_model == "claude-haiku-5-5"
    assert s.llm_ready is False


def test_conftest_default_is_configured_claude_bot():
    s = Settings()
    assert s.llm_provider == "claude" and s.llm_ready is True


def test_provider_normalized_and_validated(monkeypatch):
    assert _s(llm_provider=" OpenAI ").llm_provider == "openai"
    assert _s(llm_provider="").llm_provider == "claude"
    assert _s(llm_provider="  ").llm_provider == "claude"
    with pytest.raises(ValidationError):
        _s(llm_provider="gemini")
    # same through the real env path
    monkeypatch.setenv("LLM_PROVIDER", " OPENAI ")
    assert Settings().llm_provider == "openai"
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("value", [0, -1, 21])
def test_timeout_bounds(value):
    with pytest.raises(ValidationError):
        _s(llm_timeout_seconds=value)


def test_timeout_valid_values():
    assert _s(llm_timeout_seconds=20).llm_timeout_seconds == 20
    assert _s(llm_timeout_seconds=0.5).llm_timeout_seconds == 0.5


def test_llm_ready_per_provider():
    claude_only = dict(anthropic_api_key=KEY_VALUE)
    assert _s(llm_provider="claude", **claude_only).llm_ready is True
    assert _s(llm_provider="openai", **claude_only).llm_ready is False
    openai_only = dict(openai_api_key=KEY_VALUE)
    assert _s(llm_provider="openai", **openai_only).llm_ready is True
    assert _s(llm_provider="claude", **openai_only).llm_ready is False
    # whitespace-only key counts as missing
    assert _s(llm_provider="claude", anthropic_api_key="   ").llm_ready is False


def test_key_env_name_and_model_follow_provider():
    c = _s(llm_provider="claude")
    assert c.llm_key_env_name == "ANTHROPIC_API_KEY" and c.llm_model == c.claude_model
    o = _s(llm_provider="openai")
    assert o.llm_key_env_name == "OPENAI_API_KEY" and o.llm_model == o.openai_model


def test_repr_hides_llm_keys():
    s = _s(anthropic_api_key=KEY_VALUE, openai_api_key=KEY_VALUE)
    out = repr(s) + str(s)
    assert KEY_VALUE not in out
    assert "anthropic_api_key" not in out and "openai_api_key" not in out


def test_production_without_llm_key_still_starts():
    s = _prod_without_llm_key()
    assert s.llm_ready is False
    assert s.missing_required_secrets() == []
    check_required_settings(s)  # does not raise
    # other secrets stay fail-closed
    broken = _s(**_prod_kwargs(fb_app_secret=""))
    with pytest.raises(RuntimeError, match="FB_APP_SECRET"):
        check_required_settings(broken)


def test_warn_if_llm_disabled_names_variable_not_value(caplog):
    with caplog.at_level(logging.WARNING, logger="app"):
        warn_if_llm_disabled(_s(llm_provider="openai", anthropic_api_key=KEY_VALUE))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "OPENAI_API_KEY" in msg and "LLM_PROVIDER=openai" in msg
    assert KEY_VALUE not in msg


def test_warn_if_llm_disabled_claude_names_anthropic(caplog):
    with caplog.at_level(logging.WARNING, logger="app"):
        warn_if_llm_disabled(_s(llm_provider="claude"))
    assert "ANTHROPIC_API_KEY" in caplog.text and "LLM_PROVIDER=claude" in caplog.text


def test_no_warning_when_llm_ready(caplog):
    with caplog.at_level(logging.WARNING, logger="app"):
        warn_if_llm_disabled(_s(llm_provider="claude", anthropic_api_key=KEY_VALUE))
    assert caplog.records == []


def test_leftover_gemini_env_vars_do_not_break_startup(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "leftover-from-render")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-x")
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "15")
    s = _s(**_prod_kwargs())
    assert not hasattr(s, "gemini_api_key")  # the field is gone; leftover env is just ignored
    assert s.is_production
    assert s.missing_required_secrets() == []
