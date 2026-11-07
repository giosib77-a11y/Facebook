"""S24-10 (A-042 / N-08): no "migration not applied" fallbacks in `api/shops.py` and `api/admin.py`.

A missing table / column / RPC is a 503 (`SCHEMA_ERROR_DETAIL`, via `core/db.run` + the `main.py` APIError handler);
a failed write the seller relies on is an error, not a silent 200; the admin Python aggregation is gone (0039 RPCs
are required). Every test here fails on the pre-Stage-24 code (old behaviour in the comment). Offline: FakeSupabase.
"""
import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import app.api.admin as admin_mod
import app.api.shops as shops_mod
from app.api.admin import get_current_admin
from app.core.db import SCHEMA_ERROR_DETAIL
from app.core.security import CurrentAuth
from app.main import app as fastapi_app
from tests.conftest import USER_ID, FakeQuery, FakeSupabase

SHOP_ID = "22222222-2222-2222-2222-222222222222"
PSID = "7654321098765432"
OWNER = USER_ID
SHOP_ROW = {
    "id": SHOP_ID, "owner_id": OWNER, "name": "New shop", "description": None, "currency": "GEL",
    "subscription_tier": "free", "bot_enabled": True,
    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
}
PDF = {"file": ("k.pdf", b"%PDF-1.4", "application/pdf")}
RESOLVE_503 = "საუბრის მონიშვნა ვერ შეინახა — სცადეთ მოგვიანებით."
EXTEND_503 = "გამოწერის ვადა ვერ წაიკითხა — სცადეთ მოგვიანებით."


def _api_error(code, message="boom"):
    return APIError({"message": message, "code": code, "hint": None, "details": None})


def _assert_schema_503(r):
    assert r.status_code == 503, r.text
    assert r.json() == {"detail": SCHEMA_ERROR_DETAIL}


# ---------------------------------------------------------------- seller endpoints (api/shops.py)

def test_create_shop_without_rpc_is_503_and_no_plain_insert(client, user_db, service_db):
    # old code: 201 through a non-atomic plain insert
    user_db.responses[("shops", "select")] = []
    service_db.rpc_errors["create_shop_limited"] = _api_error("PGRST202", "Could not find the function")
    service_db.responses[("shops", "insert")] = [SHOP_ROW]

    r = client.post("/shops", json={"name": "New shop"})

    _assert_schema_503(r)
    assert service_db.calls_for("shops", "insert") == []
    assert user_db.calls_for("shops", "insert") == []
    assert len(service_db.rpc_calls) == 1


class _MissingFaqQuery(FakeQuery):
    """An update that carries `knowledge_faq` fails like PostgREST on a missing column (0027 not applied)."""

    def execute(self):
        if self.op == "update" and "knowledge_faq" in (self.payload or {}):
            self._db.faq_attempts = getattr(self._db, "faq_attempts", 0) + 1
            raise _api_error("42703", "column shops.knowledge_faq does not exist")
        return super().execute()


def _no_faq_column(service_db):
    service_db.table = lambda name: _MissingFaqQuery(service_db, name)


def test_attention_without_pause_column_is_503_and_runs_one_query(client, user_db):
    # old code: 200 with the old query (second select)
    user_db.errors[("bot_conversations", "select")] = _api_error("42703", "column bot_paused_until does not exist")
    user_db.responses[("bot_conversations", "select")] = [{"psid": PSID, "messages": [], "updated_at": "t"}]

    r = client.get(f"/shops/{SHOP_ID}/attention")

    _assert_schema_503(r)
    assert len(user_db.calls_for("bot_conversations", "select")) == 1


def test_resolve_update_failure_is_503_with_one_attempt_and_no_psid_in_log(client, user_db, service_db, caplog):
    # old code: 200 {"ok": true} after a second silent attempt
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    service_db.errors[("bot_conversations", "update")] = RuntimeError(f"db down for {PSID}")

    with caplog.at_level(logging.WARNING, logger="app"):
        r = client.post(f"/shops/{SHOP_ID}/attention/{PSID}/resolve")

    assert r.status_code == 503
    assert r.json() == {"detail": RESOLVE_503}
    assert len(service_db.calls_for("bot_conversations", "update")) == 1
    assert "attention resolve failed" in caplog.text and SHOP_ID in caplog.text
    assert PSID not in caplog.text and PSID not in r.text


def test_analytics_without_conversations_table_is_503(client, user_db):
    # old code: 200 with empty stats
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    user_db.errors[("bot_conversations", "select")] = _api_error("PGRST205", "Could not find the table")

    _assert_schema_503(client.get(f"/shops/{SHOP_ID}/analytics"))


def test_knowledge_upload_without_faq_column_is_503_and_no_second_update(client, user_db, service_db, monkeypatch):
    # old code: 200, saved without knowledge_faq on a second update
    monkeypatch.setattr(shops_mod, "extract_pdf_text", lambda content: "doc text")
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "standard"}]
    service_db.responses[("shops", "update")] = [SHOP_ROW]
    _no_faq_column(service_db)

    r = client.post(f"/shops/{SHOP_ID}/knowledge", files=PDF)

    _assert_schema_503(r)
    assert service_db.faq_attempts == 1
    assert service_db.calls_for("shops", "update") == []  # nothing was saved without the FAQ column


def test_knowledge_clear_without_faq_column_is_503_and_no_second_update(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    service_db.responses[("shops", "update")] = [SHOP_ROW]
    _no_faq_column(service_db)

    _assert_schema_503(client.delete(f"/shops/{SHOP_ID}/knowledge"))
    assert service_db.faq_attempts == 1
    assert service_db.calls_for("shops", "update") == []


def test_usage_without_upgrade_requests_table_is_503(client, user_db):
    # old code: 200 with `pending_request: null`
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "free"}]
    user_db.errors[("upgrade_requests", "select")] = _api_error("PGRST205", "Could not find the table")

    _assert_schema_503(client.get(f"/shops/{SHOP_ID}/usage"))


# ---------------------------------------------------------------- admin endpoints (api/admin.py)

@pytest.fixture
def admin_db(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(admin_mod, "get_service_client", lambda: db)
    fastapi_app.dependency_overrides[get_current_admin] = lambda: CurrentAuth(
        user_id="admin", email=None, client=db
    )
    try:
        yield db
    finally:
        fastapi_app.dependency_overrides.clear()


ADMIN_RPCS = [
    ("/admin/overview", "admin_overview_stats"),
    ("/admin/growth", "admin_growth"),
    ("/admin/shops", "admin_shop_counts"),
]


@pytest.mark.parametrize("path, fn", ADMIN_RPCS)
@pytest.mark.parametrize("code", ["PGRST202", "42883"])
def test_admin_aggregation_rpc_missing_is_503_without_python_aggregation(admin_db, path, fn, code):
    # old code: 200 computed in Python from orders / products / bot_customers
    admin_db.rpc_errors[fn] = _api_error(code, f"Could not find the function public.{fn}")
    admin_db.responses[("shops", "select")] = [
        {"id": SHOP_ID, "owner_id": OWNER, "created_at": "2026-01-01T00:00:00Z", "subscription_tier": "basic"}
    ]
    admin_db.responses[("orders", "select")] = [{"id": "o1", "shop_id": SHOP_ID, "total": 5, "status": "new"}]
    admin_db.responses[("products", "select")] = [{"id": "p1", "shop_id": SHOP_ID}]

    r = TestClient(fastapi_app).get(path)

    _assert_schema_503(r)
    assert len(admin_db.rpc_calls) == 1 and admin_db.rpc_calls[0].fn == fn
    for table in ("orders", "products", "bot_customers"):
        assert admin_db.calls_for(table, "select") == []


@pytest.mark.parametrize("path, fn", ADMIN_RPCS)
@pytest.mark.parametrize("data", [None, [], "x"])
def test_admin_aggregation_rpc_non_object_result_is_500(admin_db, path, fn, data):
    # old code: 200 from the Python aggregation
    admin_db.rpc_responses[fn] = data
    admin_db.responses[("shops", "select")] = [{"id": SHOP_ID, "owner_id": OWNER}]

    r = TestClient(fastapi_app, raise_server_exceptions=False).get(path)

    assert r.status_code == 500
    assert admin_db.calls_for("orders", "select") == []


def test_admin_rpc_helper_raises_value_error_for_non_dict(admin_db):
    admin_db.rpc_responses["admin_growth"] = [1, 2]
    with pytest.raises(ValueError, match="unexpected admin_growth result"):
        admin_mod._admin_rpc(admin_db, "admin_growth")
    assert admin_mod._admin_rpc(_dict_db({"a": 1}), "f") == {"a": 1}


def _dict_db(data):
    db = FakeSupabase()
    db.rpc_responses["f"] = data
    return db


def test_admin_upgrade_requests_without_table_is_503(admin_db):
    # old code: 200 []
    admin_db.errors[("upgrade_requests", "select")] = _api_error("PGRST205", "Could not find the table")

    _assert_schema_503(TestClient(fastapi_app).get("/admin/upgrade-requests"))


def test_extend_read_error_is_503_with_new_text_and_no_audit_row(admin_db):
    # old code: 503 "გამოწერების ცხრილი ჯერ არ არის (migration 0034)"
    owner = str(uuid.UUID(OWNER))
    admin_db.responses[("shops", "select")] = [{"subscription_tier": "basic"}]
    admin_db.errors[("subscriptions", "select")] = _api_error("PGRST205", "Could not find the table")

    r = TestClient(fastapi_app).post(f"/admin/subscriptions/{owner}/extend", json={"days": 5})

    assert r.status_code == 503
    assert r.json() == {"detail": EXTEND_503}
    assert admin_db.calls_for("subscriptions", "upsert") == []
    assert admin_db.calls_for("admin_audit_log", "insert") == []
