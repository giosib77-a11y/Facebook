"""A-043 (N-06): admin_audit_log - every admin mutation writes one audit row (best-effort, after the action).
Offline (FakeSupabase)."""
import json
import logging

import pytest
from fastapi.testclient import TestClient

import app.api.admin
from app.api.admin import get_current_admin
from app.core.security import CurrentAuth
from app.main import app as fastapi_app
from app.services import admin_audit
from tests.conftest import USER_ID, FakeSupabase

ADMIN = "admin-uuid"
OWNER = USER_ID
SHOP = "aaaaaaaa-0000-0000-0000-000000000001"
REQ = "r1"
SHOP_NAME = "Secret Boutique Name"
TABLE = "admin_audit_log"
FAILED_MSG = "admin audit write failed (PgError, action=shop.update)"


class PgError(Exception):
    def __init__(self, code):
        super().__init__("postgrest error with a payload that must never reach the log")
        self.code = code


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


def _shop_row(tier="free"):
    return {
        "id": SHOP, "owner_id": OWNER, "name": SHOP_NAME, "created_at": "2026-01-01",
        "bot_enabled": True, "subscription_tier": tier, "facebook_page_id": "p1",
    }


def _seed_request(db, tier="standard", status="pending"):
    db.responses[("upgrade_requests", "select")] = [
        {"id": REQ, "shop_id": SHOP, "requested_tier": tier, "status": status}
    ]
    db.responses[("shops", "select")] = [_shop_row()]


def _inserts(db):
    return db.calls_for(TABLE, "insert")


def _patch(payload):
    return TestClient(fastapi_app).patch(f"/admin/shops/{SHOP}", json=payload)


def _resolve(approve=True):
    return TestClient(fastapi_app).post(f"/admin/upgrade-requests/{REQ}/resolve", json={"approve": approve})


def _extend(days=30):
    return TestClient(fastapi_app).post(f"/admin/subscriptions/{OWNER}/extend", json={"days": days})


# ---- (1) PATCH /admin/shops/{id} --------------------------------------------
def test_update_shop_writes_audit_row(admin_db):
    admin_db.responses[("shops", "select")] = [_shop_row()]
    r = _patch({"bot_enabled": False})
    assert r.status_code == 200, r.text
    (q,) = _inserts(admin_db)
    assert q.payload == {
        "admin_id": ADMIN, "action": "shop.update", "target": SHOP,
        "details": {"owner_id": OWNER, "bot_enabled": False},
    }


def test_update_shop_tier_writes_only_requested_fields(admin_db):
    admin_db.responses[("shops", "select")] = [_shop_row()]
    assert _patch({"subscription_tier": "basic"}).status_code == 200
    (q,) = _inserts(admin_db)
    assert q.payload["action"] == "shop.update"
    assert q.payload["details"] == {"owner_id": OWNER, "subscription_tier": "basic"}


def test_update_shop_audit_row_written_after_the_change(admin_db):
    admin_db.responses[("shops", "select")] = [_shop_row()]
    assert _patch({"bot_enabled": False}).status_code == 200
    kinds = [(c.table, c.op) for c in admin_db.calls]
    assert kinds.index(("shops", "update")) < kinds.index((TABLE, "insert"))


@pytest.mark.parametrize("payload", [{}, {"subscription_tier": "gold"}])
def test_update_shop_400_writes_no_audit_row(admin_db, payload):
    admin_db.responses[("shops", "select")] = [_shop_row()]
    assert _patch(payload).status_code == 400
    assert _inserts(admin_db) == []


# ---- (2) DELETE /admin/shops/{id} -------------------------------------------
def test_delete_shop_writes_audit_row(admin_db):
    admin_db.responses[("shops", "select")] = [{"id": SHOP, "owner_id": OWNER}]
    r = TestClient(fastapi_app).delete(f"/admin/shops/{SHOP}")
    assert r.status_code == 204
    (q,) = _inserts(admin_db)
    assert q.payload == {
        "admin_id": ADMIN, "action": "shop.delete", "target": SHOP, "details": {"owner_id": OWNER},
    }
    kinds = [(c.table, c.op) for c in admin_db.calls]
    assert kinds.index(("shops", "delete")) < kinds.index((TABLE, "insert"))


def test_delete_shop_failure_writes_no_audit_row(admin_db):
    admin_db.responses[("shops", "select")] = [{"id": SHOP, "owner_id": OWNER}]
    admin_db.errors[("shops", "delete")] = RuntimeError("db down")
    with pytest.raises(RuntimeError):
        TestClient(fastapi_app).delete(f"/admin/shops/{SHOP}")
    assert _inserts(admin_db) == []


# ---- (3) POST /admin/upgrade-requests/{id}/resolve --------------------------
@pytest.mark.parametrize("approve,action", [(True, "upgrade_request.approve"), (False, "upgrade_request.reject")])
def test_resolve_writes_audit_row(admin_db, approve, action):
    _seed_request(admin_db, "standard")
    assert _resolve(approve).status_code == 200
    (q,) = _inserts(admin_db)
    assert q.payload == {
        "admin_id": ADMIN, "action": action, "target": REQ,
        "details": {"shop_id": SHOP, "requested_tier": "standard"},
    }


@pytest.mark.parametrize("approve", [True, False])
def test_resolve_already_processed_409_writes_no_audit_row(admin_db, approve):
    _seed_request(admin_db, "standard", status="approved")
    assert _resolve(approve).status_code == 409
    assert _inserts(admin_db) == []


def test_resolve_unknown_request_404_writes_no_audit_row(admin_db):
    assert _resolve(True).status_code == 404
    assert _inserts(admin_db) == []


# ---- (4) POST /admin/subscriptions/{owner_id}/extend ------------------------
def test_extend_writes_audit_row(admin_db):
    admin_db.responses[("shops", "select")] = [{"subscription_tier": "standard"}]
    r = _extend(7)
    assert r.status_code == 200, r.text
    body = r.json()
    (q,) = _inserts(admin_db)
    assert q.payload == {
        "admin_id": ADMIN, "action": "subscription.extend", "target": OWNER,
        "details": {"tier": "standard", "days": 7, "paid_until": body["paid_until"]},
    }


def test_extend_free_owner_400_writes_no_audit_row(admin_db):
    admin_db.responses[("shops", "select")] = [{"subscription_tier": "free"}]
    assert _extend().status_code == 400
    assert _inserts(admin_db) == []


def test_extend_subscriptions_table_missing_503_writes_no_audit_row(admin_db):
    admin_db.responses[("shops", "select")] = [{"subscription_tier": "basic"}]
    admin_db.errors[("subscriptions", "select")] = RuntimeError("relation does not exist")
    r = _extend()
    assert r.status_code == 503
    assert r.json()["detail"] == "გამოწერის ვადა ვერ წაიკითხა — სცადეთ მოგვიანებით."
    assert _inserts(admin_db) == []


# ---- (5) 404 -> no row ------------------------------------------------------
def test_unknown_shop_and_owner_404_write_no_audit_row(admin_db):
    c = TestClient(fastapi_app)
    assert c.patch(f"/admin/shops/{SHOP}", json={"bot_enabled": False}).status_code == 404
    assert c.delete(f"/admin/shops/{SHOP}").status_code == 404
    assert _extend().status_code == 404
    assert _inserts(admin_db) == []


# ---- (6) migration 0041 not applied -----------------------------------------
def test_missing_table_keeps_action_and_warns_on_every_failure(admin_db, caplog):
    admin_db.responses[("shops", "select")] = [_shop_row()]
    admin_db.errors[(TABLE, "insert")] = PgError("PGRST205")
    with caplog.at_level(logging.WARNING, logger="app"):
        r1 = _patch({"bot_enabled": False})
        r2 = _patch({"bot_enabled": True})
    assert r1.status_code == 200 and r2.status_code == 200
    assert len(_inserts(admin_db)) == 2  # tried both times; the table may appear without a restart
    assert caplog.text.count(FAILED_MSG) == 2
    assert "missing" not in caplog.text and "not applied" not in caplog.text
    assert len(admin_db.calls_for("shops", "update")) == 2  # the actions themselves were applied


def test_missing_table_postgres_code_42p01_also_warns_on_every_failure(admin_db, caplog):
    admin_db.responses[("shops", "select")] = [_shop_row()]
    admin_db.errors[(TABLE, "insert")] = PgError("42P01")
    with caplog.at_level(logging.WARNING, logger="app"):
        assert _patch({"bot_enabled": False}).status_code == 200
        assert _patch({"bot_enabled": True}).status_code == 200
    assert caplog.text.count(FAILED_MSG) == 2
    assert "missing" not in caplog.text and "not applied" not in caplog.text


# ---- (7) other write error ---------------------------------------------------
def test_other_write_error_keeps_action_and_logs_class_only(admin_db, caplog):
    admin_db.responses[("shops", "select")] = [_shop_row()]
    admin_db.errors[(TABLE, "insert")] = RuntimeError("connection reset " + SHOP + " " + OWNER)
    with caplog.at_level(logging.WARNING, logger="app"):
        r = _patch({"bot_enabled": False})
    assert r.status_code == 200, r.text
    assert "admin audit write failed (RuntimeError, action=shop.update)" in caplog.text
    assert SHOP not in caplog.text and OWNER not in caplog.text
    assert "connection reset" not in caplog.text
    assert "bot_enabled" not in caplog.text
    assert "missing" not in caplog.text and "not applied" not in caplog.text


# ---- (8) record() unit tests -------------------------------------------------
def test_record_inserts_row_and_returns_true():
    db = FakeSupabase()
    assert admin_audit.record(db, ADMIN, "shop.update", SHOP, {"bot_enabled": True, "days": 3}) is True
    (q,) = db.calls_for(TABLE, "insert")
    assert q.payload == {
        "admin_id": ADMIN, "action": "shop.update", "target": SHOP,
        "details": {"bot_enabled": True, "days": 3},
    }


def test_record_unknown_action_raises_and_writes_nothing():
    db = FakeSupabase()
    with pytest.raises(ValueError):
        admin_audit.record(db, ADMIN, "shop.explode", SHOP)
    assert db.calls == []


@pytest.mark.parametrize("key", ["email", "name", "action_link", "token"])
def test_record_unknown_detail_key_raises(key):
    db = FakeSupabase()
    with pytest.raises(ValueError):
        admin_audit.record(db, ADMIN, "shop.update", SHOP, {key: "x"})
    assert db.calls == []


@pytest.mark.parametrize("value", [{"a": 1}, ["x"], (1,), {1}, object()])
def test_record_non_scalar_value_raises(value):
    db = FakeSupabase()
    with pytest.raises(ValueError):
        admin_audit.record(db, ADMIN, "shop.update", SHOP, {"owner_id": value})
    assert db.calls == []


def test_record_drops_none_values():
    db = FakeSupabase()
    admin_audit.record(db, ADMIN, "shop.delete", SHOP, {"owner_id": None, "shop_id": SHOP})
    assert db.calls_for(TABLE, "insert")[0].payload["details"] == {"shop_id": SHOP}


def test_record_without_details_sends_empty_object():
    db = FakeSupabase()
    admin_audit.record(db, ADMIN, "seller.recovery", None)
    assert db.calls_for(TABLE, "insert")[0].payload["details"] == {}


def test_record_target_is_cut_to_64_chars_and_none_stays_none():
    db = FakeSupabase()
    admin_audit.record(db, ADMIN, "shop.update", "x" * 100)
    admin_audit.record(db, ADMIN, "shop.update", None)
    first, second = db.calls_for(TABLE, "insert")
    assert first.payload["target"] == "x" * 64
    assert second.payload["target"] is None


def test_record_never_raises_on_write_error(caplog):
    db = FakeSupabase()
    db.errors[(TABLE, "insert")] = PgError("57014")
    with caplog.at_level(logging.WARNING, logger="app"):
        assert admin_audit.record(db, ADMIN, "shop.update", SHOP, {"owner_id": OWNER}) is False
    assert "admin audit write failed (PgError, action=shop.update)" in caplog.text
    assert "postgrest error" not in caplog.text and OWNER not in caplog.text


def test_record_missing_table_returns_false_and_warns_on_every_failure(caplog):
    db = FakeSupabase()
    db.errors[(TABLE, "insert")] = PgError("PGRST205")
    with caplog.at_level(logging.WARNING, logger="app"):
        assert admin_audit.record(db, ADMIN, "shop.update", SHOP) is False
        assert admin_audit.record(db, ADMIN, "shop.update", SHOP) is False
    assert caplog.text.count(FAILED_MSG) == 2
    assert "missing" not in caplog.text and "not applied" not in caplog.text
    assert len(db.calls_for(TABLE, "insert")) == 2


def test_actions_and_detail_keys_match_the_spec():
    assert admin_audit.ACTIONS == {
        "shop.update", "shop.delete", "upgrade_request.approve", "upgrade_request.reject",
        "subscription.extend", "seller.recovery",
    }
    assert admin_audit.DETAIL_KEYS == {
        "owner_id", "shop_id", "bot_enabled", "subscription_tier", "requested_tier",
        "tier", "days", "paid_until", "email_sent",
    }


# ---- (9) read endpoints write nothing ---------------------------------------
@pytest.mark.parametrize("path", ["/admin/overview", "/admin/shops", "/admin/orders", f"/admin/shops/{SHOP}"])
def test_read_endpoints_write_no_audit_row(admin_db, path):
    admin_db.responses[("shops", "select")] = [_shop_row("basic")]
    # 0039 RPCs are required since Stage 24 (A-042): no Python-aggregation fallback
    admin_db.rpc_responses["admin_overview_stats"] = {}
    admin_db.rpc_responses["admin_shop_counts"] = {}
    r = TestClient(fastapi_app).get(path)
    assert r.status_code == 200, r.text
    assert admin_db.calls_for(TABLE, "insert") == []
    assert all(c.table != TABLE for c in admin_db.calls)


# ---- (10) no PII in any details ---------------------------------------------
def test_no_audit_details_contain_email_or_shop_name(admin_db):
    _seed_request(admin_db, "standard")
    admin_db.responses[("shops", "select")] = [_shop_row("basic")]  # not free -> extend is allowed
    assert _patch({"bot_enabled": False, "subscription_tier": "basic"}).status_code == 200
    assert _resolve(True).status_code == 200
    admin_db.responses[("upgrade_requests", "select")][0]["status"] = "pending"
    assert _resolve(False).status_code == 200
    assert _extend(5).status_code == 200
    assert TestClient(fastapi_app).delete(f"/admin/shops/{SHOP}").status_code == 204
    rows = _inserts(admin_db)
    assert len(rows) == 5
    for q in rows:
        dumped = json.dumps(q.payload["details"])
        assert "@" not in dumped
        assert SHOP_NAME not in dumped
        assert set(q.payload["details"]) <= admin_audit.DETAIL_KEYS
