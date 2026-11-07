"""Stage 24 (S24-8, A-042 / N-08): the "migration not applied" fallbacks of the services are gone - a missing
function / table is an error like any other (budget: fail-open stays, but no "off until process end"; inbox:
errors propagate; product_search: WARNING + None without backoff; admin_audit: WARNING on every failure;
subscriptions.read: always raises). Offline: fake Supabase (conftest), `APIError` for every schema error."""
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import app.api.admin
from app.api.admin import get_current_admin
from app.core.security import CurrentAuth
from app.main import app as fastapi_app
from app.services import admin_audit, budget, inbox, product_search, subscriptions
from tests.conftest import USER_ID, FakeSupabase

SHOP = "aaaaaaaa-0000-0000-0000-000000000001"
REQ = "r1"
ADMIN = "admin-uuid"
SINCE = datetime(2026, 11, 5, 0, 0, 0, tzinfo=timezone.utc)


def _api_error(code, message="boom"):
    return APIError({"code": code, "message": message, "details": None, "hint": None})


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


# ---- (1) budget: no process-wide off switch -------------------------------------------------------
def test_budget_rpc_missing_is_retried_after_the_cache_ttl_and_stays_unknown(monkeypatch, caplog):
    now = [5000.0]
    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=lambda: now[0]))
    db = FakeSupabase()
    db.rpc_errors["llm_usage_by_model"] = _api_error("PGRST202", "Could not find the function")
    with caplog.at_level(logging.WARNING, logger="app"):
        assert budget.cost_usd(db, since=SINCE) is None
        assert budget.cost_usd(db, since=SINCE) is None  # inside the TTL: cached, no log spam
        assert len(db.rpc_calls) == 1
        now[0] += budget.CACHE_SECONDS + 1
        assert budget.cost_usd(db, since=SINCE) is None
    assert len(db.rpc_calls) == 2  # the old code never called the RPC again after PGRST202
    assert _warnings(caplog) == ["llm_usage_by_model failed - LLM budget check skipped (APIError)"] * 2
    assert "not applied" not in caplog.text and "missing" not in caplog.text


def test_budget_recovers_once_the_function_exists(monkeypatch):
    now = [5000.0]
    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=lambda: now[0]))
    db = FakeSupabase()
    db.rpc_errors["llm_usage_by_model"] = _api_error("PGRST202")
    assert budget.cost_usd(db, since=SINCE) is None
    del db.rpc_errors["llm_usage_by_model"]
    db.rpc_responses["llm_usage_by_model"] = [
        {"provider": "anthropic", "model": "claude-haiku-5-5", "output_tokens": 2_000_000},
    ]
    now[0] += budget.CACHE_SECONDS + 1
    assert budget.cost_usd(db, since=SINCE) == pytest.approx(1.0)  # old code: still None (switched off)


# ---- (2) inbox.claim: errors propagate ------------------------------------------------------------
def test_inbox_claim_missing_function_raises():
    db = FakeSupabase()
    db.rpc_errors["claim_webhook_events"] = _api_error("PGRST202")
    with pytest.raises(APIError):
        inbox.claim(db, 5)  # old code: [] with one WARNING
    assert len(db.rpc_calls) == 1


# ---- (3) product_search: WARNING + None, the next call retries at once ------------------------------
def test_product_search_missing_function_is_none_and_retried_immediately(monkeypatch, caplog):
    product_search._reset_for_tests()
    db = FakeSupabase()
    db.rpc_errors["search_products"] = _api_error("PGRST202")
    monkeypatch.setattr(product_search, "get_service_client", lambda: db)
    monkeypatch.setattr(product_search, "_now", lambda: 1000.0)
    try:
        with caplog.at_level(logging.WARNING, logger="app.product_search"):
            assert product_search.search(SHOP, "red shirt", 5) is None
            assert product_search.search(SHOP, "red shirt", 5) is None  # old code: 600 s backoff, no RPC
    finally:
        product_search._reset_for_tests()
    assert len(db.rpc_calls) == 2
    assert _warnings(caplog) == ["search_products RPC failed (APIError) - in-memory search"]  # throttled (60 s)
    assert "not applied" not in caplog.text


# ---- (4) admin_audit: every failure is one WARNING ---------------------------------------------------
def test_admin_audit_missing_table_warns_on_every_failure(caplog):
    db = FakeSupabase()
    db.errors[("admin_audit_log", "insert")] = _api_error("PGRST205", "Could not find the table")
    with caplog.at_level(logging.WARNING, logger="app"):
        assert admin_audit.record(db, ADMIN, "shop.update", SHOP) is False
        assert admin_audit.record(db, ADMIN, "shop.update", SHOP) is False
    assert _warnings(caplog) == ["admin audit write failed (APIError, action=shop.update)"] * 2  # old: 1 "missing"
    assert "not applied" not in caplog.text and "missing" not in caplog.text
    assert len(db.calls_for("admin_audit_log", "insert")) == 2


# ---- (5) subscriptions.read: always raises -----------------------------------------------------------
@pytest.mark.parametrize("exc", [_api_error("PGRST205"), RuntimeError("down")])
def test_subscriptions_read_error_propagates(exc):
    db = FakeSupabase()
    db.errors[("subscriptions", "select")] = exc
    with pytest.raises(type(exc)):
        subscriptions.read(db, USER_ID)  # old code: None
    with pytest.raises(type(exc)):
        subscriptions.read(db, USER_ID)  # a second call raises again (no "once" state)


# ---- (6) approve: a failed subscriptions read stops everything before any write ---------------------
@pytest.fixture
def admin_db(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(app.api.admin, "get_service_client", lambda: db)
    fastapi_app.dependency_overrides[get_current_admin] = lambda: CurrentAuth(
        user_id=ADMIN, email=None, client=db
    )
    try:
        yield db
    finally:
        fastapi_app.dependency_overrides.clear()


def _seed_approve(db):
    db.responses[("upgrade_requests", "select")] = [
        {"id": REQ, "shop_id": SHOP, "requested_tier": "standard", "status": "pending"}
    ]
    db.responses[("shops", "select")] = [{
        "id": SHOP, "owner_id": USER_ID, "name": "s", "created_at": "2026-01-01",
        "bot_enabled": True, "subscription_tier": "standard", "facebook_page_id": "p1",
    }]


@pytest.mark.parametrize("exc, status_code", [(RuntimeError("down"), 500), (_api_error("PGRST205"), 503)])
def test_approve_with_failed_subscriptions_read_changes_nothing(admin_db, exc, status_code):
    _seed_approve(admin_db)
    admin_db.errors[("subscriptions", "select")] = exc
    r = TestClient(fastapi_app, raise_server_exceptions=False).post(
        f"/admin/upgrade-requests/{REQ}/resolve", json={"approve": True}
    )
    assert r.status_code == status_code, r.text  # old code: 200 + a fresh 30 days
    assert admin_db.calls_for("shops", "update") == []
    assert admin_db.calls_for("upgrade_requests", "update") == []
    assert admin_db.calls_for("subscriptions", "upsert") == []
