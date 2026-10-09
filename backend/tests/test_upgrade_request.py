"""S12-3: upgrade requests are written by the backend (service client) after an RLS ownership check."""
from tests.conftest import USER_ID  # noqa: F401  (fixtures)

A = "22222222-2222-2222-2222-222222222222"
B = "33333333-3333-3333-3333-333333333333"
STRANGER = "99999999-9999-9999-9999-999999999999"


def test_request_writes_via_service_client_and_cancels_all_owner_pending(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"id": A}, {"id": B}]
    r = client.post(f"/shops/{A}/upgrade-request", json={"tier": "standard"})
    assert r.status_code == 200, r.text
    assert user_db.calls_for("upgrade_requests", "insert") == []
    (ins,) = service_db.calls_for("upgrade_requests", "insert")
    assert ins.payload == {"shop_id": A, "requested_tier": "standard", "status": "pending"}
    (cancel,) = service_db.calls_for("upgrade_requests", "update")
    assert cancel.payload == {"status": "cancelled"}
    assert ("in", "shop_id", [A, B]) in cancel.filters  # per-account: every shop of the owner
    assert ("eq", "status", "pending") in cancel.filters


def test_request_for_foreign_shop_is_404_and_writes_nothing(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"id": A}]
    r = client.post(f"/shops/{STRANGER}/upgrade-request", json={"tier": "basic"})
    assert r.status_code == 404
    assert service_db.calls_for("upgrade_requests", "insert") == []
    assert service_db.calls_for("upgrade_requests", "update") == []


def test_request_free_or_unknown_tier_rejected(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"id": A}]
    for tier in ("free", "platinum"):
        assert client.post(f"/shops/{A}/upgrade-request", json={"tier": tier}).status_code == 400
    assert service_db.calls_for("upgrade_requests", "insert") == []


def test_cancel_failure_is_500_and_no_second_pending(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"id": A}]
    service_db.errors[("upgrade_requests", "update")] = RuntimeError("db down")
    r = client.post(f"/shops/{A}/upgrade-request", json={"tier": "basic"})
    assert r.status_code == 500
    assert service_db.calls_for("upgrade_requests", "insert") == []


def test_request_is_rate_limited(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"id": A}]
    codes = [client.post(f"/shops/{A}/upgrade-request", json={"tier": "basic"}).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10
    assert codes[10] == 429
