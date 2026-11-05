"""Stage 21 (S21-1): worker / CSP / USD ბიუჯეტი / ფასების Settings + conftest-ის kwargs."""
import json
import os

import pytest
from pydantic import ValidationError

from app.config import DEFAULT_LLM_PRICES, Settings

from tests.conftest import FakeSupabase


def _s(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


# ---- default-ები ----

def test_stage21_defaults(monkeypatch):
    monkeypatch.delenv("WEBHOOK_INBOX_ENABLED")  # conftest-ი ტესტებში "false"-ზე ამაგრებს
    s = _s()
    assert s.webhook_inbox_enabled is None
    assert s.bot_max_concurrency == 8
    assert s.webhook_poll_seconds == 10.0
    assert s.webhook_max_attempts == 3
    assert s.webhook_claim_stale_seconds == 180
    assert s.csp_report_only is False
    assert s.llm_daily_usd_cap == 1.0
    assert s.llm_daily_usd_shop_divisor == 10.0
    assert s.llm_monthly_usd_free == 0.30
    assert s.llm_monthly_usd_basic == 2.50
    assert s.llm_monthly_usd_standard == 8.0
    assert s.llm_monthly_usd_business == 25.0
    assert s.llm_prices == DEFAULT_LLM_PRICES


def test_no_per_owner_daily_usd_setting():
    # მფლობელის ცვლილება 2026-11-05: დღიური ჭერი მაღაზიაზეა (თვიური ÷ გამყოფი)
    assert not hasattr(_s(), "llm_daily_usd_per_owner")


def test_conftest_pins_inbox_off_in_tests():
    assert os.environ["WEBHOOK_INBOX_ENABLED"] == "false"


# ---- webhook_inbox_active ----

@pytest.mark.parametrize(
    ("app_env", "explicit", "expected"),
    [
        ("production", None, True),
        ("development", None, False),
        ("production", False, False),
        ("production", True, True),
        ("development", True, True),
        ("development", False, False),
    ],
)
def test_webhook_inbox_active(app_env, explicit, expected):
    s = _s(app_env=app_env, webhook_inbox_enabled=explicit)
    assert s.webhook_inbox_active is expected


def test_webhook_inbox_enabled_empty_env_is_none(monkeypatch):
    monkeypatch.setenv("WEBHOOK_INBOX_ENABLED", "")
    s = _s(app_env="production")
    assert s.webhook_inbox_enabled is None
    assert s.webhook_inbox_active is True


def test_webhook_inbox_enabled_false_env(monkeypatch):
    monkeypatch.setenv("WEBHOOK_INBOX_ENABLED", "false")
    assert _s(app_env="production").webhook_inbox_active is False


# ---- საზღვრები ----

@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("bot_max_concurrency", 0),
        ("bot_max_concurrency", 33),
        ("webhook_poll_seconds", 0.5),
        ("webhook_poll_seconds", 301),
        ("webhook_max_attempts", 0),
        ("webhook_max_attempts", 11),
        ("webhook_claim_stale_seconds", 59),
        ("webhook_claim_stale_seconds", 3601),
    ],
)
def test_worker_bounds_rejected(field, bad):
    with pytest.raises(ValidationError):
        _s(**{field: bad})


def test_worker_bounds_edges_accepted():
    s = _s(bot_max_concurrency=32, webhook_claim_stale_seconds=60, webhook_max_attempts=10)
    assert (s.bot_max_concurrency, s.webhook_claim_stale_seconds, s.webhook_max_attempts) == (32, 60, 10)


# ---- USD ბიუჯეტი ----

def test_monthly_usd_budget_by_tier():
    s = _s()
    assert s.llm_monthly_usd_budget("free") == 0.30
    assert s.llm_monthly_usd_budget("basic") == 2.50
    assert s.llm_monthly_usd_budget("standard") == 8.0
    assert s.llm_monthly_usd_budget("business") == 25.0
    assert s.llm_monthly_usd_budget("nonsense") == 0.30
    assert s.llm_monthly_usd_budget(None) == 0.30


def test_shop_daily_cap_is_monthly_divided_by_divisor():
    s = _s()
    assert s.llm_daily_usd_shop_cap("free") == pytest.approx(0.03)
    assert s.llm_daily_usd_shop_cap("basic") == pytest.approx(0.25)
    assert s.llm_daily_usd_shop_cap("standard") == pytest.approx(0.80)
    assert s.llm_daily_usd_shop_cap("business") == pytest.approx(2.50)
    assert s.llm_daily_usd_shop_cap("nonsense") == pytest.approx(0.03)


def test_shop_daily_cap_follows_monthly_env():
    s = _s(llm_monthly_usd_basic=5.0, llm_daily_usd_shop_divisor=5)
    assert s.llm_daily_usd_shop_cap("basic") == pytest.approx(1.0)


def test_shop_daily_cap_disabled_when_divisor_zero():
    s = _s(llm_daily_usd_shop_divisor=0)
    assert s.llm_daily_usd_shop_cap("business") == 0.0


@pytest.mark.parametrize(
    "field",
    [
        "llm_daily_usd_cap", "llm_daily_usd_shop_divisor", "llm_monthly_usd_free",
        "llm_monthly_usd_basic", "llm_monthly_usd_standard", "llm_monthly_usd_business",
    ],
)
@pytest.mark.parametrize("bad", [-0.01, float("inf"), float("nan")])
def test_usd_settings_reject_negative_and_non_finite(field, bad):
    with pytest.raises(ValidationError):
        _s(**{field: bad})


def test_usd_zero_means_disabled_and_is_accepted():
    s = _s(llm_monthly_usd_free=0, llm_daily_usd_cap=0)
    assert s.llm_monthly_usd_budget("free") == 0.0
    assert s.llm_daily_usd_cap == 0.0


# ---- LLM_PRICES ----

_CLAUDE = {"input": 1.0, "output": 2.0, "cache_read": 0.1, "cache_write": 1.5}


def test_default_prices_shape():
    assert set(DEFAULT_LLM_PRICES) == {"claude-haiku-5-5", "gpt-6-luna"}
    for prices in DEFAULT_LLM_PRICES.values():
        assert set(prices) == {"input", "output", "cache_read", "cache_write"}


def test_prices_empty_env_uses_defaults(monkeypatch):
    monkeypatch.setenv("LLM_PRICES", "")
    assert _s().llm_prices == DEFAULT_LLM_PRICES


def test_prices_env_json_replaces_only_that_model(monkeypatch):
    monkeypatch.setenv("LLM_PRICES", json.dumps({"claude-haiku-5-5": _CLAUDE}))
    s = _s()
    assert s.llm_prices["claude-haiku-5-5"] == _CLAUDE
    assert s.llm_prices["gpt-6-luna"] == DEFAULT_LLM_PRICES["gpt-6-luna"]


def test_prices_env_adds_new_model(monkeypatch):
    monkeypatch.setenv("LLM_PRICES", json.dumps({"new-model": _CLAUDE}))
    s = _s()
    assert s.llm_prices["new-model"] == _CLAUDE
    assert set(s.llm_prices) == {"claude-haiku-5-5", "gpt-6-luna", "new-model"}


def test_prices_dict_kwarg_merged_and_defaults_not_mutated():
    before = json.dumps(DEFAULT_LLM_PRICES, sort_keys=True)
    s = _s(llm_prices={"claude-haiku-5-5": dict(_CLAUDE)})
    assert s.llm_prices["claude-haiku-5-5"] == _CLAUDE
    s.llm_prices["gpt-6-luna"]["input"] = 99.0
    assert json.dumps(DEFAULT_LLM_PRICES, sort_keys=True) == before


@pytest.mark.parametrize(
    "bad",
    [
        {"claude-haiku-5-5": {"input": 1.0, "output": 2.0, "cache_read": 0.1}},  # გასაღები აკლია
        {"claude-haiku-5-5": {**_CLAUDE, "extra": 1.0}},  # ზედმეტი გასაღები
        {"claude-haiku-5-5": {**_CLAUDE, "input": -1.0}},  # უარყოფითი
        {"claude-haiku-5-5": {**_CLAUDE, "input": "secret-abc"}},  # არა რიცხვი
        {"claude-haiku-5-5": {**_CLAUDE, "input": float("inf")}},  # არა finite
        {"claude-haiku-5-5": {**_CLAUDE, "input": True}},  # bool არ არის ფასი
        {"claude-haiku-5-5": "secret-abc"},  # მოდელი არა-ობიექტი
        ["secret-abc"],  # ზედა დონე არა-ობიექტი
    ],
)
def test_prices_invalid_raises_without_leaking_value(monkeypatch, bad):
    monkeypatch.setenv("LLM_PRICES", json.dumps(bad) if not isinstance(bad, str) else bad)
    with pytest.raises(ValidationError) as ei:
        _s()
    text = str(ei.value)
    assert "LLM_PRICES" in text
    assert "secret-abc" not in text


def test_prices_not_json_raises_without_leaking_value(monkeypatch):
    monkeypatch.setenv("LLM_PRICES", "{secret-abc not json")
    with pytest.raises(ValidationError) as ei:
        _s()
    text = str(ei.value)
    assert "LLM_PRICES" in text
    assert "secret-abc" not in text


def test_llm_price_exact_match():
    s = _s()
    assert s.llm_price("claude-haiku-5-5") == DEFAULT_LLM_PRICES["claude-haiku-5-5"]
    assert s.llm_price("gpt-6-luna") == DEFAULT_LLM_PRICES["gpt-6-luna"]


def test_llm_price_unknown_is_per_field_max_of_known():
    s = _s(llm_prices={
        "claude-haiku-5-5": {"input": 1.0, "output": 0.5, "cache_read": 0.01, "cache_write": 0.2},
        "gpt-6-luna": {"input": 0.1, "output": 3.0, "cache_read": 0.5, "cache_write": 0.1},
    })
    assert s.llm_price("unknown-model") == {
        "input": 1.0, "output": 3.0, "cache_read": 0.5, "cache_write": 0.2,
    }


# ---- FakeSupabase kwargs ----

def test_fake_query_records_upsert_and_insert_kwargs():
    db = FakeSupabase()
    db.table("t").upsert([], on_conflict="a", ignore_duplicates=True).execute()
    db.table("t").insert({"x": 1}).execute()
    assert db.calls[0].kwargs == {"on_conflict": "a", "ignore_duplicates": True}
    assert db.calls[1].kwargs == {}
    db.table("t").insert({"x": 1}, count="exact").execute()
    assert db.calls[2].kwargs == {"count": "exact"}
