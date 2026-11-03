"""S19-9 (A-029 / N-19): shop limit check + INSERT run atomically in the `create_shop_limited` RPC."""
import logging

import pytest
from postgrest.exceptions import APIError

from app.api import shops
from tests.conftest import USER_ID

SHOP_ID = "11111111-1111-1111-1111-111111111111"
TS = {"created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}
LIMIT_TEXT = (
    "პაკეტის ლიმიტი: მეტი მაღაზიის დასამატებლად განაახლე პაკეტი "
    "(სტანდარტი — 2 მაღაზია, ბიზნესი — ულიმიტო)."
)


def _row(tier="free"):
    return {
        "id": SHOP_ID, "owner_id": USER_ID, "name": "New shop", "description": None,
        "currency": "GEL", "subscription_tier": tier, "bot_enabled": True, **TS,
    }


@pytest.fixture(autouse=True)
def _reset_missing_flag(monkeypatch):
    # raising=False: on the old code the attribute does not exist
    monkeypatch.setattr(shops, "_CREATE_SHOP_RPC_MISSING", False, raising=False)


def _api_error(message, code):
    return APIError({"message": message, "code": code, "hint": None, "details": None})


def _rpc(db):
    return [c for c in db.rpc_calls if c.fn == "create_shop_limited"]


def test_free_owner_creates_shop_via_rpc_once(client, user_db, service_db):
    user_db.responses[("shops", "select")] = []
    service_db.rpc_responses["create_shop_limited"] = [_row("free")]

    resp = client.post("/shops", json={"name": "New shop", "description": "d", "currency": "USD"})

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == SHOP_ID
    (call,) = _rpc(service_db)
    assert call.params == {
        "p_owner": USER_ID, "p_name": "New shop", "p_description": "d",
        "p_currency": "USD", "p_tier": "free", "p_limit": 1,
    }
    assert service_db.calls_for("shops", "insert") == []
    assert user_db.calls_for("shops", "insert") == []


def test_rpc_limit_error_race_is_403_with_limit_text(client, user_db, service_db):
    """The pre-check passed (stale read), the RPC refused under its lock."""
    user_db.responses[("shops", "select")] = []
    service_db.rpc_errors["create_shop_limited"] = _api_error("shop_limit_reached", "P0001")

    resp = client.post("/shops", json={"name": "New shop"})

    assert resp.status_code == 403
    assert resp.json()["detail"] == LIMIT_TEXT
    assert len(_rpc(service_db)) == 1
    assert service_db.calls_for("shops", "insert") == []


def test_business_owner_passes_no_limit(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"subscription_tier": "business"}] * 3
    service_db.rpc_responses["create_shop_limited"] = [_row("business")]

    resp = client.post("/shops", json={"name": "New shop"})

    assert resp.status_code == 201, resp.text
    (call,) = _rpc(service_db)
    assert call.params["p_limit"] is None
    assert call.params["p_tier"] == "business"


def test_missing_function_falls_back_to_insert_and_warns_once(client, user_db, service_db, caplog):
    user_db.responses[("shops", "select")] = []
    service_db.rpc_errors["create_shop_limited"] = _api_error(
        "Could not find the function public.create_shop_limited", "PGRST202"
    )
    service_db.responses[("shops", "insert")] = [_row("free")]

    with caplog.at_level(logging.WARNING, logger="app"):
        r1 = client.post("/shops", json={"name": "New shop"})
        r2 = client.post("/shops", json={"name": "New shop"})

    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text
    assert len(service_db.calls_for("shops", "insert")) == 2
    assert len(_rpc(service_db)) == 1  # after the flag is set the RPC is not called again
    warnings = [r for r in caplog.records if "create_shop_limited missing" in r.getMessage()]
    assert len(warnings) == 1
    assert "migration 0032" in warnings[0].getMessage()
    insert = service_db.calls_for("shops", "insert")[0]
    assert insert.payload["owner_id"] == USER_ID
    assert insert.payload["subscription_tier"] == "free"


def test_payload_owner_id_is_ignored(client, user_db, service_db):
    user_db.responses[("shops", "select")] = []
    service_db.rpc_responses["create_shop_limited"] = [_row()]

    resp = client.post(
        "/shops",
        json={"name": "New shop", "owner_id": "99999999-9999-9999-9999-999999999999"},
    )

    assert resp.status_code == 201, resp.text
    (call,) = _rpc(service_db)
    assert call.params["p_owner"] == USER_ID
    assert "owner_id" not in call.params


def test_pre_check_403_unchanged_and_rpc_not_called(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"subscription_tier": "free"}]

    resp = client.post("/shops", json={"name": "Second"})

    assert resp.status_code == 403
    assert resp.json()["detail"] == LIMIT_TEXT
    assert _rpc(service_db) == []
    assert service_db.calls_for("shops", "insert") == []


def test_other_rpc_error_is_400_and_does_not_leak_text(client, user_db, service_db, caplog):
    user_db.responses[("shops", "select")] = []
    service_db.rpc_errors["create_shop_limited"] = _api_error('relation "secret_table" broke', "XX000")

    with caplog.at_level(logging.WARNING, logger="app"):
        resp = client.post("/shops", json={"name": "New shop"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "მაღაზიის შექმნა ვერ მოხერხდა"
    assert "secret_table" not in resp.text
    assert service_db.calls_for("shops", "insert") == []
    assert any("APIError" in r.getMessage() for r in caplog.records)
    # not the "function missing" case -> the RPC stays in use
    assert shops._CREATE_SHOP_RPC_MISSING is False


def test_non_postgrest_rpc_error_is_400(client, user_db, service_db):
    user_db.responses[("shops", "select")] = []
    service_db.rpc_errors["create_shop_limited"] = RuntimeError("connection reset")

    resp = client.post("/shops", json={"name": "New shop"})

    assert resp.status_code == 400
    assert "connection reset" not in resp.text


def test_empty_rpc_data_is_400(client, user_db, service_db):
    user_db.responses[("shops", "select")] = []
    service_db.rpc_responses["create_shop_limited"] = []

    resp = client.post("/shops", json={"name": "New shop"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "მაღაზიის შექმნა ვერ მოხერხდა"
