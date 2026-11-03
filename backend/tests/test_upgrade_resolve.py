"""A-024 (N-06, part): resolve_upgrade_request only processes `pending` requests."""
import pytest
from fastapi.testclient import TestClient

import app.api.admin
from app.api.admin import get_current_admin
from app.core.security import CurrentAuth
from app.main import app as fastapi_app
from tests.conftest import USER_ID, FakeSupabase

OWNER = USER_ID
SHOP = "aaaaaaaa-0000-0000-0000-000000000001"
REQ = "r1"
PENDING_FILTER = ("eq", "status", "pending")


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


def _request(status, tier="standard"):
    return {"id": REQ, "shop_id": SHOP, "requested_tier": tier, "status": status}


def _seed(db, status, tier="standard"):
    db.responses[("upgrade_requests", "select")] = [_request(status, tier)]
    db.responses[("shops", "select")] = [
        {
            "id": SHOP, "owner_id": OWNER, "name": "s", "created_at": "2026-01-01",
            "bot_enabled": True, "subscription_tier": "free", "facebook_page_id": "p1",
        }
    ]


def _resolve(approve):
    return TestClient(fastapi_app).post(
        f"/admin/upgrade-requests/{REQ}/resolve", json={"approve": approve}
    )


def _no_writes(db):
    return (
        db.calls_for("shops", "update") == []
        and db.calls_for("upgrade_requests", "update") == []
    )


@pytest.mark.parametrize("status", ["rejected", "cancelled", "approved"])
def test_approve_non_pending_is_409_and_changes_nothing(admin_db, status):
    _seed(admin_db, status)
    r = _resolve(True)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "მოთხოვნა უკვე დამუშავებულია"
    assert admin_db.calls_for("shops", "update") == []
    assert admin_db.calls_for("upgrade_requests", "update") == []
    assert _no_writes(admin_db)


def test_reject_already_rejected_is_409(admin_db):
    _seed(admin_db, "rejected")
    r = _resolve(False)
    assert r.status_code == 409, r.text
    assert _no_writes(admin_db)


def test_missing_status_is_not_processed(admin_db):
    _seed(admin_db, None)
    assert _resolve(True).status_code == 409
    assert _no_writes(admin_db)


def test_pending_approve_changes_tier_on_all_owner_shops(admin_db):
    _seed(admin_db, "pending")
    r = _resolve(True)
    assert r.status_code == 200, r.text
    tier_updates = [
        u for u in admin_db.calls_for("shops", "update")
        if u.payload == {"subscription_tier": "standard"}
    ]
    assert len(tier_updates) == 1
    assert ("eq", "owner_id", OWNER) in tier_updates[0].filters
    (status_update,) = admin_db.calls_for("upgrade_requests", "update")
    assert status_update.payload["status"] == "approved"
    assert ("eq", "id", REQ) in status_update.filters
    assert PENDING_FILTER in status_update.filters


def test_pending_reject_marks_rejected_with_pending_filter(admin_db):
    _seed(admin_db, "pending")
    r = _resolve(False)
    assert r.status_code == 200, r.text
    assert admin_db.calls_for("shops", "update") == []
    (status_update,) = admin_db.calls_for("upgrade_requests", "update")
    assert status_update.payload["status"] == "rejected"
    assert ("eq", "id", REQ) in status_update.filters
    assert PENDING_FILTER in status_update.filters


def test_unknown_request_is_404(admin_db):
    admin_db.responses[("upgrade_requests", "select")] = []
    r = _resolve(True)
    assert r.status_code == 404
    assert _no_writes(admin_db)


def test_bad_tier_is_400(admin_db):
    _seed(admin_db, "pending", tier="platinum")
    r = _resolve(True)
    assert r.status_code == 400
    assert _no_writes(admin_db)
