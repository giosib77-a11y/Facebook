"""S20-5 (A-039): DELETE /shops/{id}/customers/{psid} - the seller erases one customer's data.

Ownership via the user client (RLS); writes via the service client with explicit shop_id + psid
filters. bot_conversations is deleted; bot_customers is anonymized (psid -> "del:<hex>") so the
monthly-limit counter (count(*) / created_at order) is not reset (S20-18). Fake Supabase only (tests/conftest.py); nothing leaves the process.
"""
import logging
import re

import pytest

SHOP_ID = "22222222-2222-2222-2222-222222222222"
PSID = "7654321098765432"


def _url(psid=PSID, shop_id=SHOP_ID):
    return f"/shops/{shop_id}/customers/{psid}"


def _owner(user_db):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID}]


def _deletes(db):
    return [c for c in db.calls if c.op == "delete"]


def test_owner_deletes_conversation_and_anonymizes_counter(client, user_db, service_db):
    _owner(user_db)
    r = client.delete(_url())
    assert r.status_code == 200 and r.json() == {"ok": True}
    # bot_conversations: hard delete by shop_id + psid (unchanged)
    (d,) = service_db.calls_for("bot_conversations", "delete")
    assert ("eq", "shop_id", SHOP_ID) in d.filters
    assert ("eq", "psid", PSID) in d.filters
    # bot_customers: NOT deleted (the monthly-limit counter must not reset) - psid is replaced
    assert service_db.calls_for("bot_customers", "delete") == []
    (u,) = service_db.calls_for("bot_customers", "update")
    assert re.fullmatch(r"del:[0-9a-f]{32}", u.payload["psid"])
    assert set(u.payload) == {"psid"}
    assert ("eq", "shop_id", SHOP_ID) in u.filters
    assert ("eq", "psid", PSID) in u.filters
    # writes go through the service client only; the user client just checked ownership
    assert _deletes(user_db) == []
    assert [c for c in user_db.calls if c.op != "select"] == []
    (own,) = user_db.calls_for("shops", "select")
    assert ("eq", "id", SHOP_ID) in own.filters


def test_anonymized_psid_is_not_reusable_as_the_original(client, user_db, service_db):
    _owner(user_db)
    assert client.delete(_url()).status_code == 200
    (u,) = service_db.calls_for("bot_customers", "update")
    assert PSID not in u.payload["psid"]


def test_each_delete_gets_a_fresh_anonymous_psid(client, user_db, service_db):
    _owner(user_db)
    assert client.delete(_url()).status_code == 200
    assert client.delete(_url("1111")).status_code == 200
    first, second = service_db.calls_for("bot_customers", "update")
    assert first.payload["psid"] != second.payload["psid"]


@pytest.mark.parametrize("psid", ["abc", "1" * 33, "12 34", "12-34", "١٢٣"])
def test_invalid_psid_is_400_before_any_db_call(client, user_db, service_db, psid):
    r = client.delete(_url(psid))
    assert r.status_code == 400
    assert user_db.calls == [] and service_db.calls == []


def test_32_digit_psid_is_accepted(client, user_db, service_db):
    _owner(user_db)
    assert client.delete(_url("9" * 32)).status_code == 200
    assert len(_deletes(service_db)) == 1  # bot_conversations only; bot_customers is anonymized
    assert len(service_db.calls_for("bot_customers", "update")) == 1


def test_foreign_shop_is_404_and_nothing_is_deleted(client, user_db, service_db):
    user_db.responses[("shops", "select")] = []  # RLS hides somebody else's shop
    r = client.delete(_url())
    assert r.status_code == 404
    assert _deletes(service_db) == []


def test_invalid_shop_uuid_is_422(client, user_db, service_db):
    r = client.delete(_url(shop_id="not-a-uuid"))
    assert r.status_code == 422
    assert service_db.calls == []


@pytest.mark.parametrize("table,op", [("bot_conversations", "delete"), ("bot_customers", "update")])
def test_delete_error_is_500_and_log_has_no_psid(client, user_db, service_db, caplog, table, op):
    _owner(user_db)
    service_db.errors[(table, op)] = RuntimeError(f"db down for {PSID}")
    with caplog.at_level(logging.INFO, logger="app"):
        r = client.delete(_url())
    assert r.status_code == 500
    assert "ვერ მოხერხდა" in r.text
    assert "customer data deletion failed" in caplog.text and "RuntimeError" in caplog.text
    assert PSID not in caplog.text
    assert "customer data deleted" not in caplog.text


def test_success_logs_shop_only(client, user_db, service_db, caplog):
    _owner(user_db)
    with caplog.at_level(logging.INFO, logger="app"):
        assert client.delete(_url()).status_code == 200
    assert f"customer data deleted (shop={SHOP_ID})" in caplog.text
    assert PSID not in caplog.text
