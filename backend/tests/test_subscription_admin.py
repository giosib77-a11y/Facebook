"""A-036 (N-02): admin side — approve / PATCH tier write `subscriptions`, /admin/shops shows paid_until,
POST /admin/subscriptions/{owner_id}/extend. Offline (FakeSupabase)."""
import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import app.api.admin
from app.api.admin import get_current_admin
from app.core.db import SCHEMA_ERROR_DETAIL
from app.core.security import CurrentAuth
from app.main import app as fastapi_app
from tests.conftest import USER_ID, FakeSupabase

OWNER = USER_ID
SHOP = "aaaaaaaa-0000-0000-0000-000000000001"
REQ = "r1"
D = timedelta(days=1)


@pytest.fixture
def admin_db(monkeypatch):
    db = FakeSupabase()
    db.rpc_responses["admin_shop_counts"] = {}  # 0039 RPC is required by GET /admin/shops (Stage 24, A-042)
    monkeypatch.setattr(app.api.admin, "get_service_client", lambda: db)
    fastapi_app.dependency_overrides[get_current_admin] = lambda: CurrentAuth(
        user_id="admin", email=None, client=db
    )
    try:
        yield db
    finally:
        fastapi_app.dependency_overrides.clear()


def _shop_row(tier="free"):
    return {
        "id": SHOP, "owner_id": OWNER, "name": "s", "created_at": "2026-01-01",
        "bot_enabled": True, "subscription_tier": tier, "facebook_page_id": "p1",
    }


def _seed_request(db, tier="standard", current_tier="free"):
    db.responses[("upgrade_requests", "select")] = [
        {"id": REQ, "shop_id": SHOP, "requested_tier": tier, "status": "pending"}
    ]
    db.responses[("shops", "select")] = [_shop_row(current_tier)]


def _resolve(approve=True):
    return TestClient(fastapi_app).post(
        f"/admin/upgrade-requests/{REQ}/resolve", json={"approve": approve}
    )


def _close_to_now_plus(value: str, days: int, tol_seconds: int = 120):
    got = datetime.fromisoformat(value)
    want = datetime.now(timezone.utc) + timedelta(days=days)
    assert abs((got - want).total_seconds()) < tol_seconds


# ---- approve ---------------------------------------------------------------
def test_approve_writes_subscription_with_30_days(admin_db):
    _seed_request(admin_db, "standard")
    r = _resolve(True)
    assert r.status_code == 200, r.text
    (q,) = admin_db.calls_for("subscriptions", "upsert")
    assert q.payload["owner_id"] == OWNER
    assert q.payload["tier"] == "standard"
    _close_to_now_plus(q.payload["paid_until"], 30)


def test_approve_writes_subscription_before_mirror_update(admin_db):
    _seed_request(admin_db, "standard")
    assert _resolve(True).status_code == 200
    kinds = [(c.table, c.op) for c in admin_db.calls]
    assert kinds.index(("subscriptions", "upsert")) < kinds.index(("shops", "update"))


def test_approve_same_tier_with_active_expiry_adds_30_to_current(admin_db):
    until = datetime.now(timezone.utc) + 10 * D
    _seed_request(admin_db, "standard", current_tier="standard")
    admin_db.responses[("subscriptions", "select")] = [
        {"tier": "standard", "paid_until": until.isoformat()}
    ]
    assert _resolve(True).status_code == 200
    (q,) = admin_db.calls_for("subscriptions", "upsert")
    assert datetime.fromisoformat(q.payload["paid_until"]) == until + 30 * D


def test_approve_other_tier_restarts_from_now(admin_db):
    until = datetime.now(timezone.utc) + 10 * D
    _seed_request(admin_db, "business", current_tier="standard")
    admin_db.responses[("subscriptions", "select")] = [
        {"tier": "standard", "paid_until": until.isoformat()}
    ]
    assert _resolve(True).status_code == 200
    (q,) = admin_db.calls_for("subscriptions", "upsert")
    assert q.payload["tier"] == "business"
    _close_to_now_plus(q.payload["paid_until"], 30)


def test_approve_expired_row_restarts_from_now(admin_db):
    _seed_request(admin_db, "standard", current_tier="standard")
    admin_db.responses[("subscriptions", "select")] = [
        {"tier": "standard", "paid_until": (datetime.now(timezone.utc) - 5 * D).isoformat()}
    ]
    assert _resolve(True).status_code == 200
    (q,) = admin_db.calls_for("subscriptions", "upsert")
    _close_to_now_plus(q.payload["paid_until"], 30)


def test_approve_subscription_write_failure_does_not_block_approve(admin_db, caplog):
    _seed_request(admin_db, "standard")
    admin_db.errors[("subscriptions", "upsert")] = RuntimeError("no such table")
    with caplog.at_level(logging.WARNING, logger="app"):
        r = _resolve(True)
    assert r.status_code == 200, r.text
    tier_updates = [
        u for u in admin_db.calls_for("shops", "update") if u.payload == {"subscription_tier": "standard"}
    ]
    assert len(tier_updates) == 1
    (status_update,) = admin_db.calls_for("upgrade_requests", "update")
    assert status_update.payload["status"] == "approved"
    assert "subscriptions write failed" in caplog.text
    assert "no such table" not in caplog.text


def test_approve_subscription_read_failure_is_500_and_nothing_changes(admin_db):
    _seed_request(admin_db, "standard")
    admin_db.errors[("subscriptions", "select")] = RuntimeError("relation missing")
    r = TestClient(fastapi_app, raise_server_exceptions=False).post(
        f"/admin/upgrade-requests/{REQ}/resolve", json={"approve": True}
    )
    assert r.status_code == 500, r.text  # old code: 200 and a fresh 30 days (the renewal's remaining days were lost)
    assert admin_db.calls_for("shops", "update") == []
    assert admin_db.calls_for("upgrade_requests", "update") == []
    assert admin_db.calls_for("subscriptions", "upsert") == []


def test_reject_does_not_touch_subscriptions(admin_db):
    _seed_request(admin_db, "standard")
    assert _resolve(False).status_code == 200
    assert admin_db.calls_for("subscriptions", "upsert") == []


def test_non_pending_request_writes_no_subscription(admin_db):
    _seed_request(admin_db, "standard")
    admin_db.responses[("upgrade_requests", "select")][0]["status"] = "approved"
    assert _resolve(True).status_code == 409
    assert admin_db.calls_for("subscriptions", "upsert") == []


# ---- PATCH /admin/shops/{id} ------------------------------------------------
def _patch(payload):
    return TestClient(fastapi_app).patch(f"/admin/shops/{SHOP}", json=payload)


def test_patch_tier_writes_subscription_with_30_days(admin_db):
    admin_db.responses[("shops", "select")] = [_shop_row("free")]
    r = _patch({"subscription_tier": "basic"})
    assert r.status_code == 200, r.text
    (q,) = admin_db.calls_for("subscriptions", "upsert")
    assert q.payload["owner_id"] == OWNER and q.payload["tier"] == "basic"
    _close_to_now_plus(q.payload["paid_until"], 30)


def test_patch_tier_keeps_active_expiry(admin_db):
    until = datetime.now(timezone.utc) + 12 * D
    admin_db.responses[("shops", "select")] = [_shop_row("basic")]
    admin_db.responses[("subscriptions", "select")] = [{"tier": "basic", "paid_until": until.isoformat()}]
    assert _patch({"subscription_tier": "business"}).status_code == 200
    (q,) = admin_db.calls_for("subscriptions", "upsert")
    assert q.payload["tier"] == "business"
    assert datetime.fromisoformat(q.payload["paid_until"]) == until


def test_patch_to_free_clears_expiry(admin_db):
    admin_db.responses[("shops", "select")] = [_shop_row("basic")]
    admin_db.responses[("subscriptions", "select")] = [
        {"tier": "basic", "paid_until": (datetime.now(timezone.utc) + 5 * D).isoformat()}
    ]
    assert _patch({"subscription_tier": "free"}).status_code == 200
    (q,) = admin_db.calls_for("subscriptions", "upsert")
    assert q.payload["tier"] == "free" and q.payload["paid_until"] is None


def test_patch_bot_enabled_only_does_not_touch_subscriptions(admin_db):
    admin_db.responses[("shops", "select")] = [_shop_row("basic")]
    assert _patch({"bot_enabled": False}).status_code == 200
    assert admin_db.calls_for("subscriptions", "upsert") == []
    assert admin_db.calls_for("subscriptions", "select") == []


def test_patch_tier_subscription_failure_still_200(admin_db, caplog):
    admin_db.responses[("shops", "select")] = [_shop_row("free")]
    admin_db.errors[("subscriptions", "upsert")] = RuntimeError("boom")
    with caplog.at_level(logging.WARNING, logger="app"):
        r = _patch({"subscription_tier": "basic"})
    assert r.status_code == 200, r.text
    assert [u.payload for u in admin_db.calls_for("shops", "update")
            if u.payload == {"subscription_tier": "basic"}]
    assert "subscriptions write failed" in caplog.text


@pytest.mark.parametrize(
    "exc, code",
    [
        (APIError({"code": "PGRST205", "message": "x", "details": None, "hint": None}), 503),
        (RuntimeError("relation missing"), 500),
    ],
)
def test_patch_tier_subscription_read_failure_is_an_error_and_nothing_changes(admin_db, exc, code):
    admin_db.responses[("shops", "select")] = [_shop_row("free")]
    admin_db.errors[("subscriptions", "select")] = exc
    r = TestClient(fastapi_app, raise_server_exceptions=False).patch(
        f"/admin/shops/{SHOP}", json={"bot_enabled": False, "subscription_tier": "basic"}
    )
    assert r.status_code == code, r.text  # old code: 200 / tier already changed without paid_until
    if code == 503:
        assert r.json() == {"detail": SCHEMA_ERROR_DETAIL}
    assert admin_db.calls_for("shops", "update") == []
    assert admin_db.calls_for("subscriptions", "upsert") == []
    assert admin_db.calls_for("admin_audit_log", "insert") == []


# ---- GET /admin/shops -------------------------------------------------------
def test_admin_shops_lists_owner_id_and_paid_until(admin_db):
    admin_db.responses[("shops", "select")] = [_shop_row("basic")]
    admin_db.responses[("subscriptions", "select")] = [
        {"owner_id": OWNER, "paid_until": "2026-12-01T00:00:00+00:00"}
    ]
    r = TestClient(fastapi_app).get("/admin/shops")
    assert r.status_code == 200, r.text
    (row,) = r.json()
    assert row["owner_id"] == OWNER
    assert row["paid_until"] == "2026-12-01T00:00:00+00:00"
    assert row["tier"] == "basic"
    (q,) = admin_db.calls_for("subscriptions", "select")  # one query for all shops
    assert q.table == "subscriptions"


def test_admin_shops_without_subscription_row_has_null_paid_until(admin_db):
    admin_db.responses[("shops", "select")] = [_shop_row("free")]
    (row,) = TestClient(fastapi_app).get("/admin/shops").json()
    assert row["owner_id"] == OWNER and row["paid_until"] is None


def test_admin_shops_table_error_is_an_error(admin_db):
    admin_db.responses[("shops", "select")] = [_shop_row("basic")]
    admin_db.errors[("subscriptions", "select")] = RuntimeError("relation does not exist")
    r = TestClient(fastapi_app, raise_server_exceptions=False).get("/admin/shops")
    assert r.status_code == 500, r.text  # old code: 200 with `paid_until: null`
    assert not isinstance(r.json(), list)


# ---- POST /admin/subscriptions/{owner_id}/extend ---------------------------
def _extend(days=30, owner=OWNER):
    return TestClient(fastapi_app).post(f"/admin/subscriptions/{owner}/extend", json={"days": days})


def test_extend_adds_days_to_active_expiry(admin_db):
    until = datetime.now(timezone.utc) + 10 * D
    admin_db.responses[("shops", "select")] = [{"subscription_tier": "standard"}]
    admin_db.responses[("subscriptions", "select")] = [{"tier": "standard", "paid_until": until.isoformat()}]
    r = _extend(7)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["owner_id"] == OWNER and body["tier"] == "standard"
    assert datetime.fromisoformat(body["paid_until"]) == until + 7 * D
    (q,) = admin_db.calls_for("subscriptions", "upsert")
    assert q.payload["paid_until"] == body["paid_until"] and q.payload["tier"] == "standard"


def test_extend_expired_starts_from_now(admin_db):
    admin_db.responses[("shops", "select")] = [{"subscription_tier": "basic"}]
    admin_db.responses[("subscriptions", "select")] = [
        {"tier": "basic", "paid_until": (datetime.now(timezone.utc) - 20 * D).isoformat()}
    ]
    r = _extend(15)
    assert r.status_code == 200, r.text
    _close_to_now_plus(r.json()["paid_until"], 15)


def test_extend_without_subscription_row_starts_from_now(admin_db):
    admin_db.responses[("shops", "select")] = [{"subscription_tier": "basic"}]
    r = _extend(30)
    assert r.status_code == 200, r.text
    _close_to_now_plus(r.json()["paid_until"], 30)


def test_extend_uses_owners_highest_tier(admin_db):
    admin_db.responses[("shops", "select")] = [
        {"subscription_tier": "free"}, {"subscription_tier": "business"}
    ]
    r = _extend(5)
    assert r.status_code == 200, r.text
    assert r.json()["tier"] == "business"


def test_extend_free_owner_is_400(admin_db):
    admin_db.responses[("shops", "select")] = [{"subscription_tier": "free"}]
    r = _extend(5)
    assert r.status_code == 400
    assert r.json()["detail"] == "უფასო პაკეტს ვადა არ აქვს"
    assert admin_db.calls_for("subscriptions", "upsert") == []


def test_extend_owner_without_shops_is_404(admin_db):
    admin_db.responses[("shops", "select")] = []
    r = _extend(5)
    assert r.status_code == 404
    assert r.json()["detail"] == "მფლობელი ვერ მოიძებნა"
    assert admin_db.calls_for("subscriptions", "upsert") == []


@pytest.mark.parametrize("days", [0, -1, 367])
def test_extend_days_out_of_range_is_422(admin_db, days):
    admin_db.responses[("shops", "select")] = [{"subscription_tier": "basic"}]
    assert _extend(days).status_code == 422
    assert admin_db.calls_for("subscriptions", "upsert") == []


@pytest.mark.parametrize("days", [1, 366])
def test_extend_days_bounds_accepted(admin_db, days):
    admin_db.responses[("shops", "select")] = [{"subscription_tier": "basic"}]
    assert _extend(days).status_code == 200


def test_extend_bad_owner_id_is_422(admin_db):
    assert _extend(5, owner="not-a-uuid").status_code == 422


def test_extend_non_integer_days_is_422(admin_db):
    r = TestClient(fastapi_app).post(f"/admin/subscriptions/{OWNER}/extend", json={"days": "abc"})
    assert r.status_code == 422


def test_extend_read_error_is_503_and_nothing_written(admin_db):
    admin_db.responses[("shops", "select")] = [{"subscription_tier": "basic"}]
    admin_db.errors[("subscriptions", "select")] = RuntimeError("relation does not exist")
    r = _extend(5)
    assert r.status_code == 503
    assert r.json()["detail"] == "გამოწერის ვადა ვერ წაიკითხა — სცადეთ მოგვიანებით."
    assert admin_db.calls_for("subscriptions", "upsert") == []


def test_extend_write_error_is_503(admin_db):
    admin_db.responses[("shops", "select")] = [{"subscription_tier": "basic"}]
    admin_db.errors[("subscriptions", "upsert")] = RuntimeError("relation does not exist")
    r = _extend(5)
    assert r.status_code == 503
    assert r.json()["detail"] == "გამოწერის ვადა ვერ წაიკითხა — სცადეთ მოგვიანებით."


def test_extend_requires_admin(client):
    """Regular seller (not in ADMIN_USER_IDS) gets 403 — no admin override installed here."""
    r = client.post(f"/admin/subscriptions/{OWNER}/extend", json={"days": 5})
    assert r.status_code == 403
