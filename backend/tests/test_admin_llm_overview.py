"""S20-9 / S21-7 (A-037 / A-048): GET /admin/overview carries `llm` (platform USD spend) for the admin banner.
Offline (FakeSupabase); admin only."""
import pytest
from fastapi.testclient import TestClient

import app.api.admin
from app.api.admin import get_current_admin
from app.core.security import CurrentAuth, get_current_auth
from app.main import app as fastapi_app
from app.services import budget
from tests.conftest import FakeSupabase

CAP = 1.0  # default LLM_DAILY_USD_CAP


def _spend(usd):
    """llm_usage_by_model rows costing `usd` at the default Claude output price ($0.50 / 1M tokens)."""
    return [{
        "provider": "anthropic", "model": "claude-haiku-5-5", "input_tokens": 0,
        "output_tokens": round(usd * 2_000_000), "cache_read_tokens": 0, "cache_write_tokens": 0,
    }]


@pytest.fixture
def admin_db(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(app.api.admin, "get_service_client", lambda: db)
    fastapi_app.dependency_overrides[get_current_admin] = lambda: CurrentAuth(
        user_id="admin", email=None, client=db
    )
    try:
        yield db
    finally:
        fastapi_app.dependency_overrides.clear()


def _overview():
    return TestClient(fastapi_app).get("/admin/overview")


def test_overview_has_llm_block_and_keeps_existing_fields(admin_db):
    admin_db.rpc_responses["llm_usage_by_model"] = _spend(0.1234)

    r = _overview()

    assert r.status_code == 200
    body = r.json()
    assert body["llm"] == {
        "today_usd": 0.1234, "month_usd": 0.1234, "daily_cap_usd": CAP,
        "kill_switch": False, "alert": False,
    }
    for key in ("total_shops", "total_sellers", "connected_shops", "total_products",
                "total_orders", "orders_30d", "revenue", "mrr", "tier_counts"):
        assert key in body


def test_overview_queries_platform_totals_not_one_shop_or_owner(admin_db):
    admin_db.rpc_responses["llm_usage_by_model"] = _spend(0.01)

    _overview()

    rpcs = [c for c in admin_db.rpc_calls if c.fn == "llm_usage_by_model"]
    assert rpcs and all(c.params["p_owner"] is None and c.params["p_shop"] is None for c in rpcs)


def test_overview_alert_at_80_percent_of_daily_cap(admin_db):
    admin_db.rpc_responses["llm_usage_by_model"] = _spend(CAP * 0.8)

    llm = _overview().json()["llm"]

    assert llm["alert"] is True
    assert llm["kill_switch"] is False


def test_overview_no_alert_just_below_80_percent(admin_db):
    admin_db.rpc_responses["llm_usage_by_model"] = _spend(CAP * 0.8 - 0.01)

    assert _overview().json()["llm"]["alert"] is False


def test_overview_kill_switch_raises_alert(admin_db, monkeypatch):
    admin_db.rpc_responses["llm_usage_by_model"] = _spend(0.001)
    s = budget.get_settings().model_copy(update={"llm_kill_switch": True})
    monkeypatch.setattr(budget, "get_settings", lambda: s)

    llm = _overview().json()["llm"]

    assert llm["kill_switch"] is True
    assert llm["alert"] is True


def test_overview_migration_missing_gives_null_usd(admin_db):
    class Missing(Exception):
        code = "PGRST202"

    admin_db.rpc_errors["llm_usage_by_model"] = Missing("function not found")

    r = _overview()

    assert r.status_code == 200
    llm = r.json()["llm"]
    assert llm["today_usd"] is None and llm["month_usd"] is None
    assert llm["alert"] is False
    assert llm["daily_cap_usd"] == CAP


def test_overview_migration_missing_with_kill_switch_still_alerts(admin_db, monkeypatch):
    class Missing(Exception):
        code = "PGRST202"

    admin_db.rpc_errors["llm_usage_by_model"] = Missing("function not found")
    s = budget.get_settings().model_copy(update={"llm_kill_switch": True})
    monkeypatch.setattr(budget, "get_settings", lambda: s)

    llm = _overview().json()["llm"]

    assert llm["today_usd"] is None
    assert llm["kill_switch"] is True
    assert llm["alert"] is True


def test_overview_requires_admin(monkeypatch, user_db):
    s = app.api.admin.get_settings().model_copy(update={"admin_user_ids": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"})
    monkeypatch.setattr(app.api.admin, "get_settings", lambda: s)
    fastapi_app.dependency_overrides[get_current_auth] = lambda: CurrentAuth(
        user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", email="x@test.local", client=user_db
    )
    try:
        r = _overview()
    finally:
        fastapi_app.dependency_overrides.clear()
    assert r.status_code == 403
    assert "llm" not in r.json()
