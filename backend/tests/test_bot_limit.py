"""S12-2: bot count is capped by the owner's tier on every downgrade path (seller, admin tier, approve)."""
import pytest
from fastapi.testclient import TestClient

import app.api.admin
from app.api.admin import get_current_admin
from app.core.security import CurrentAuth
from app.main import app as fastapi_app
from app.services.bot_limits import enforce_bot_limit
from tests.conftest import USER_ID, FakeSupabase

OWNER = USER_ID
A, B, C = "aaaaaaaa-0000-0000-0000-000000000001", "bbbbbbbb-0000-0000-0000-000000000002", "cccccccc-0000-0000-0000-000000000003"


def shop(sid, created, enabled, tier="free", name=None):
    return {
        "id": sid, "name": name or sid[:1], "created_at": created, "bot_enabled": enabled,
        "subscription_tier": tier, "owner_id": OWNER, "facebook_page_id": "p" + sid[:1],
    }


def bot_off_updates(db):
    return [u for u in db.calls_for("shops", "update") if u.payload == {"bot_enabled": False}]


def assert_scoped_off(update, ids):
    assert ("eq", "owner_id", OWNER) in update.filters
    assert ("in", "id", ids) in update.filters


# ---- helper ---------------------------------------------------------------
def test_free_keeps_oldest_enabled_and_disables_newer():
    db = FakeSupabase()
    db.responses[("shops", "select")] = [shop(A, "2026-01-01", True), shop(B, "2026-02-01", True)]
    out = enforce_bot_limit(db, OWNER)
    assert [d["id"] for d in out] == [B]
    (u,) = bot_off_updates(db)
    assert_scoped_off(u, [B])


def test_disabled_old_shop_does_not_occupy_the_slot():
    """Scenario B of the audit: A is old but its bot is off, B's bot is the only one running."""
    db = FakeSupabase()
    db.responses[("shops", "select")] = [shop(A, "2026-01-01", False), shop(B, "2026-02-01", True)]
    assert enforce_bot_limit(db, OWNER) == []
    assert bot_off_updates(db) == []


def test_standard_allows_two_disables_third():
    db = FakeSupabase()
    db.responses[("shops", "select")] = [
        shop(A, "2026-01-01", True, "standard"), shop(B, "2026-02-01", True, "standard"),
        shop(C, "2026-03-01", True, "standard"),
    ]
    assert [d["id"] for d in enforce_bot_limit(db, OWNER)] == [C]


def test_business_unlimited_and_highest_tier_wins():
    db = FakeSupabase()
    db.responses[("shops", "select")] = [
        shop(A, "2026-01-01", True, "free"), shop(B, "2026-02-01", True, "business"),
    ]
    assert enforce_bot_limit(db, OWNER) == []
    assert bot_off_updates(db) == []


# ---- path 1: seller downgrade ----------------------------------------------
def test_seller_downgrade_disables_excess_only(client, service_db):
    rows = [shop(A, "2026-01-01", False), shop(B, "2026-02-01", True)]
    service_db.responses[("shops", "update")] = rows
    service_db.responses[("shops", "select")] = rows
    r = client.post(f"/shops/{A}/downgrade-free")
    assert r.status_code == 200, r.text
    assert r.json()["bot_disabled"] == []
    assert bot_off_updates(service_db) == []


def test_seller_downgrade_db_error_is_500_not_ok(client, service_db):
    rows = [shop(A, "2026-01-01", True), shop(B, "2026-02-01", True)]
    service_db.responses[("shops", "update")] = rows
    service_db.responses[("shops", "select")] = rows
    service_db.errors[("shops", "select")] = RuntimeError("db down")
    r = client.post(f"/shops/{A}/downgrade-free")
    assert r.status_code == 500


# ---- paths 2 and 3: admin ---------------------------------------------------
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


def test_admin_tier_downgrade_disables_excess_bots(admin_db):
    admin_db.responses[("shops", "select")] = [shop(A, "2026-01-01", True), shop(B, "2026-02-01", True)]
    r = TestClient(fastapi_app).patch(f"/admin/shops/{A}", json={"subscription_tier": "free"})
    assert r.status_code == 200, r.text
    (u,) = bot_off_updates(admin_db)
    assert_scoped_off(u, [B])


def test_admin_approve_downgrade_request_disables_excess_bots(admin_db):
    admin_db.responses[("upgrade_requests", "select")] = [{"id": "r1", "shop_id": A, "requested_tier": "basic"}]
    admin_db.responses[("shops", "select")] = [
        shop(A, "2026-01-01", True, "basic"), shop(B, "2026-02-01", True, "basic"),
    ]
    r = TestClient(fastapi_app).post("/admin/upgrade-requests/r1/resolve", json={"approve": True})
    assert r.status_code == 200, r.text
    (u,) = bot_off_updates(admin_db)
    assert_scoped_off(u, [B])


def test_admin_tier_change_db_error_is_500(admin_db):
    admin_db.responses[("shops", "select")] = [shop(A, "2026-01-01", True)]
    # first select (owner lookup) ok, enforce's select fails
    calls = {"n": 0}
    orig = admin_db.table

    def table(name):
        q = orig(name)
        if name == "shops":
            real = q.execute

            def execute():
                if q.op == "select":
                    calls["n"] += 1
                    if calls["n"] == 2:
                        raise RuntimeError("db down")
                return real()
            q.execute = execute
        return q

    admin_db.table = table
    r = TestClient(fastapi_app).patch(f"/admin/shops/{A}", json={"subscription_tier": "free"})
    assert r.status_code == 500
