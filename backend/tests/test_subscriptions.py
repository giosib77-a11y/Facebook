"""A-036 (N-02): services/subscriptions.py + seller side (/shops/{id}/usage, downgrade-free).

All offline: FakeSupabase from conftest (`user_db` = RLS client, `service_db` = service_role client).
"""
import logging
from datetime import datetime, timedelta, timezone

import pytest

from app.services import subscriptions
from app.services.subscriptions import next_paid_until, status_for
from tests.conftest import USER_ID, FakeSupabase

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
D = timedelta(days=1)
SHOP = "aaaaaaaa-0000-0000-0000-000000000001"
TABLE_MSG = "subscriptions table unavailable (migration 0034 not applied?) - expiry disabled"


@pytest.fixture(autouse=True)
def _fresh_warning_flag(monkeypatch):
    monkeypatch.setattr(subscriptions, "_READ_WARNED", False)


# ---- next_paid_until ---------------------------------------------------------
def test_constants():
    assert subscriptions.PAID_PERIOD_DAYS == 30
    assert subscriptions.EXPIRY_WARNING_DAYS == 3


def test_free_has_no_expiry_even_with_active_paid_row():
    cur = {"tier": "standard", "paid_until": (NOW + 10 * D).isoformat()}
    assert next_paid_until(cur, "free", renewal=True, now=NOW) is None
    assert next_paid_until(cur, "free", renewal=False, now=NOW) is None


def test_new_paid_without_row_is_now_plus_30():
    assert next_paid_until(None, "basic", renewal=True, now=NOW) == NOW + 30 * D
    assert next_paid_until(None, "basic", renewal=False, now=NOW) == NOW + 30 * D


def test_renewal_same_tier_active_adds_30_to_current():
    until = NOW + 10 * D
    cur = {"tier": "basic", "paid_until": until.isoformat()}
    assert next_paid_until(cur, "basic", renewal=True, now=NOW) == until + 30 * D


def test_renewal_other_tier_active_starts_from_now():
    cur = {"tier": "basic", "paid_until": (NOW + 10 * D).isoformat()}
    assert next_paid_until(cur, "standard", renewal=True, now=NOW) == NOW + 30 * D


def test_manual_change_keeps_active_paid_expiry():
    until = NOW + 10 * D
    cur = {"tier": "basic", "paid_until": until.isoformat()}
    assert next_paid_until(cur, "business", renewal=False, now=NOW) == until
    assert next_paid_until(cur, "basic", renewal=False, now=NOW) == until


def test_expired_or_free_or_broken_row_starts_from_now():
    expired = {"tier": "basic", "paid_until": (NOW - D).isoformat()}
    assert next_paid_until(expired, "basic", renewal=True, now=NOW) == NOW + 30 * D
    assert next_paid_until(expired, "standard", renewal=False, now=NOW) == NOW + 30 * D
    free_row = {"tier": "free", "paid_until": (NOW + 10 * D).isoformat()}
    assert next_paid_until(free_row, "basic", renewal=True, now=NOW) == NOW + 30 * D
    no_date = {"tier": "basic", "paid_until": None}
    assert next_paid_until(no_date, "basic", renewal=True, now=NOW) == NOW + 30 * D
    garbage = {"tier": "basic", "paid_until": "not-a-date"}
    assert next_paid_until(garbage, "basic", renewal=False, now=NOW) == NOW + 30 * D


def test_accepts_z_suffix_naive_and_datetime_values():
    until = NOW + 5 * D
    z = {"tier": "basic", "paid_until": until.strftime("%Y-%m-%dT%H:%M:%SZ")}
    assert next_paid_until(z, "basic", renewal=True, now=NOW) == until + 30 * D
    naive = {"tier": "basic", "paid_until": until.replace(tzinfo=None)}
    assert next_paid_until(naive, "basic", renewal=True, now=NOW) == until + 30 * D


# ---- status_for --------------------------------------------------------------
def test_status_two_days_left_is_expiring_soon():
    s = status_for("basic", (NOW + 2 * D).isoformat(), NOW)
    assert s == {"paid_until": (NOW + 2 * D).isoformat(), "expires_soon": True, "expired": False}


def test_status_four_days_left_is_not_expiring_soon():
    s = status_for("basic", (NOW + 4 * D).isoformat(), NOW)
    assert s["expires_soon"] is False and s["expired"] is False


def test_status_exactly_three_days_is_expiring_soon_exactly_now_is_expired():
    assert status_for("basic", NOW + 3 * D, NOW)["expires_soon"] is True
    s = status_for("basic", NOW, NOW)
    assert s["expired"] is True and s["expires_soon"] is False


def test_status_past_is_expired():
    s = status_for("standard", (NOW - D).isoformat(), NOW)
    assert s["expired"] is True and s["expires_soon"] is False
    assert s["paid_until"] == (NOW - D).isoformat()


def test_status_free_and_missing_date_report_nothing():
    nothing = {"paid_until": None, "expires_soon": False, "expired": False}
    assert status_for("free", (NOW + D).isoformat(), NOW) == nothing
    assert status_for("basic", None, NOW) == nothing
    assert status_for("basic", "garbage", NOW) == nothing


# ---- read / write / apply_tier ----------------------------------------------
def test_read_returns_row_and_filters_by_owner():
    db = FakeSupabase()
    db.responses[("subscriptions", "select")] = [{"tier": "basic", "paid_until": "2026-12-01T00:00:00+00:00"}]
    assert subscriptions.read(db, USER_ID) == {"tier": "basic", "paid_until": "2026-12-01T00:00:00+00:00"}
    (q,) = db.calls_for("subscriptions", "select")
    assert ("eq", "owner_id", USER_ID) in q.filters


def test_read_missing_row_is_none_without_warning(caplog):
    db = FakeSupabase()
    with caplog.at_level(logging.WARNING, logger="app"):
        assert subscriptions.read(db, USER_ID) is None
    assert TABLE_MSG not in caplog.text


def test_read_error_is_none_and_warns_once_per_process(caplog):
    db = FakeSupabase()
    db.errors[("subscriptions", "select")] = RuntimeError("relation does not exist")
    with caplog.at_level(logging.WARNING, logger="app"):
        assert subscriptions.read(db, USER_ID) is None
        assert subscriptions.read(db, USER_ID) is None
    assert caplog.text.count(TABLE_MSG) == 1


def test_read_strict_raises_on_error():
    db = FakeSupabase()
    db.errors[("subscriptions", "select")] = RuntimeError("down")
    with pytest.raises(RuntimeError):
        subscriptions.read(db, USER_ID, strict=True)


class _FailsOnce(FakeSupabase):
    """First subscriptions select fails, the next succeed (transient error)."""

    def __init__(self):
        super().__init__()
        self.failed = False

    def table(self, name):
        if name == "subscriptions" and not self.failed:
            self.failed = True
            self.errors[("subscriptions", "select")] = RuntimeError("blip")
        elif name == "subscriptions":
            self.errors.pop(("subscriptions", "select"), None)
        return super().table(name)


def test_read_recovers_after_first_failure():
    db = _FailsOnce()
    db.responses[("subscriptions", "select")] = [{"tier": "basic", "paid_until": None}]
    assert subscriptions.read(db, USER_ID) is None
    assert subscriptions.read(db, USER_ID) == {"tier": "basic", "paid_until": None}


def test_write_upserts_row_with_iso_dates():
    db = FakeSupabase()
    until = NOW + 30 * D
    assert subscriptions.write(db, USER_ID, "basic", until) is True
    (q,) = db.calls_for("subscriptions", "upsert")
    assert q.payload["owner_id"] == USER_ID
    assert q.payload["tier"] == "basic"
    assert q.payload["paid_until"] == until.isoformat()
    assert datetime.fromisoformat(q.payload["updated_at"]).tzinfo is not None


def test_write_free_stores_null_paid_until():
    db = FakeSupabase()
    assert subscriptions.write(db, USER_ID, "free", None) is True
    (q,) = db.calls_for("subscriptions", "upsert")
    assert q.payload["tier"] == "free" and q.payload["paid_until"] is None


def test_write_error_returns_false_and_logs_owner_and_class_only(caplog):
    db = FakeSupabase()
    db.errors[("subscriptions", "upsert")] = RuntimeError("secret-detail-from-db")
    with caplog.at_level(logging.WARNING, logger="app"):
        assert subscriptions.write(db, USER_ID, "basic", NOW) is False
    assert USER_ID in caplog.text and "RuntimeError" in caplog.text
    assert "secret-detail-from-db" not in caplog.text


def test_apply_tier_renewal_extends_active_same_tier():
    db = FakeSupabase()
    until = datetime.now(timezone.utc) + 10 * D
    db.responses[("subscriptions", "select")] = [{"tier": "basic", "paid_until": until.isoformat()}]
    got = subscriptions.apply_tier(db, USER_ID, "basic", renewal=True)
    assert got == until + 30 * D
    (q,) = db.calls_for("subscriptions", "upsert")
    assert q.payload["paid_until"] == (until + 30 * D).isoformat()


def test_apply_tier_survives_write_failure():
    db = FakeSupabase()
    db.errors[("subscriptions", "upsert")] = RuntimeError("down")
    got = subscriptions.apply_tier(db, USER_ID, "basic", renewal=True)
    assert got is not None  # computed value is returned, write failure only logs


# ---- GET /shops/{id}/usage ---------------------------------------------------
def _seed_usage(user_db, tier, sub=None):
    user_db.responses[("shops", "select")] = [{"subscription_tier": tier}]
    if sub is not None:
        user_db.responses[("subscriptions", "select")] = sub


def test_usage_returns_expiry_fields_from_subscriptions_row(client, user_db):
    until = datetime.now(timezone.utc) + 2 * D
    _seed_usage(user_db, "standard", [{"tier": "standard", "paid_until": until.isoformat()}])
    r = client.get(f"/shops/{SHOP}/usage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert datetime.fromisoformat(body["paid_until"]) == until
    assert body["expires_soon"] is True
    assert body["expired"] is False
    # RLS client, filtered by the caller's own owner id
    (q,) = user_db.calls_for("subscriptions", "select")
    assert ("eq", "owner_id", USER_ID) in q.filters


def test_usage_far_future_is_neither_soon_nor_expired(client, user_db):
    until = datetime.now(timezone.utc) + 20 * D
    _seed_usage(user_db, "basic", [{"tier": "basic", "paid_until": until.isoformat()}])
    body = client.get(f"/shops/{SHOP}/usage").json()
    assert body["expires_soon"] is False and body["expired"] is False
    assert body["paid_until"] is not None


def test_usage_past_paid_until_is_expired_before_cron(client, user_db):
    until = datetime.now(timezone.utc) - timedelta(hours=2)
    _seed_usage(user_db, "basic", [{"tier": "basic", "paid_until": until.isoformat()}])
    body = client.get(f"/shops/{SHOP}/usage").json()
    assert body["expired"] is True and body["expires_soon"] is False


def test_usage_free_has_null_expiry_and_skips_subscriptions_query(client, user_db):
    _seed_usage(user_db, "free", [{"tier": "basic", "paid_until": "2099-01-01T00:00:00+00:00"}])
    body = client.get(f"/shops/{SHOP}/usage").json()
    assert body["paid_until"] is None
    assert body["expires_soon"] is False and body["expired"] is False
    assert user_db.calls_for("subscriptions", "select") == []


def test_usage_without_subscriptions_row_is_null(client, user_db):
    _seed_usage(user_db, "basic", [])
    body = client.get(f"/shops/{SHOP}/usage").json()
    assert body["paid_until"] is None
    assert body["expires_soon"] is False and body["expired"] is False


def test_usage_table_error_is_null_false_and_200(client, user_db, caplog):
    _seed_usage(user_db, "basic")
    user_db.errors[("subscriptions", "select")] = RuntimeError("relation does not exist")
    with caplog.at_level(logging.WARNING, logger="app"):
        r = client.get(f"/shops/{SHOP}/usage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["paid_until"] is None
    assert body["expires_soon"] is False and body["expired"] is False
    assert body["tier"] == "basic"
    assert TABLE_MSG in caplog.text


def test_usage_other_fields_unchanged(client, user_db):
    _seed_usage(user_db, "basic", [])
    body = client.get(f"/shops/{SHOP}/usage").json()
    for key in ("tier", "tier_label", "monthly_customers", "customer_limit", "products",
                "product_limit", "bulk_import", "pending_request", "prices", "payment_iban",
                "payment_contact"):
        assert key in body


# ---- POST /shops/{id}/downgrade-free ----------------------------------------
def _seed_downgrade(service_db):
    rows = [{
        "id": SHOP, "name": "a", "created_at": "2026-01-01", "bot_enabled": True,
        "subscription_tier": "free", "owner_id": USER_ID, "facebook_page_id": "p1",
    }]
    service_db.responses[("shops", "update")] = rows
    service_db.responses[("shops", "select")] = rows


def test_downgrade_writes_free_subscription_via_service_client(client, user_db, service_db):
    _seed_downgrade(service_db)
    r = client.post(f"/shops/{SHOP}/downgrade-free")
    assert r.status_code == 200, r.text
    (q,) = service_db.calls_for("subscriptions", "upsert")
    assert q.payload["owner_id"] == USER_ID
    assert q.payload["tier"] == "free"
    assert q.payload["paid_until"] is None
    assert user_db.calls_for("subscriptions", "upsert") == []


def test_downgrade_subscription_write_failure_keeps_response(client, service_db, caplog):
    _seed_downgrade(service_db)
    service_db.errors[("subscriptions", "upsert")] = RuntimeError("no such table")
    with caplog.at_level(logging.WARNING, logger="app"):
        r = client.post(f"/shops/{SHOP}/downgrade-free")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["tier"] == "free"
    assert "subscriptions write failed" in caplog.text
    assert "no such table" not in caplog.text
