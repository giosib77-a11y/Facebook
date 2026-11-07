"""Stage 24 (A-042 / N-08): a missing table / column / function is a bug or a skipped migration, not a signal to
silently fall back to old behaviour - `core.db.run` re-raises it, `main.py` answers 503 with one text, and the
P1 / O1 / F1 / V1 fallbacks are gone. Offline: fake Supabase (conftest), APIError for every schema error."""
import logging
import re
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import app.api.admin as admin_mod
import app.api.facebook as fb_api
import app.main as main_mod
from app.api.admin import get_current_admin
from app.core.db import SCHEMA_ERROR_DETAIL, SCHEMA_MISSING_CODES, is_schema_missing, run
from app.core.security import CurrentAuth
from app.main import app as fastapi_app
from app.services import vision
from tests.conftest import USER_ID, FakeSupabase

SHOP = "22222222-2222-2222-2222-222222222222"
PRODUCT = "33333333-3333-3333-3333-333333333333"
ORDER = "44444444-4444-4444-4444-444444444444"
KEY = "55555555-5555-4555-8555-555555555555"
PSID = "9876543210123456"
LIMIT_DETAIL = "პაკეტის ლიმიტი ვერ შემოწმდა — სცადე ცოტა ხანში."
ALL_CODES = ["PGRST202", "PGRST204", "PGRST205", "42P01", "42703", "42883"]


def _api_error(code, message="boom"):
    return APIError({"code": code, "message": message, "details": None, "hint": None})


class _Failing:
    """A query whose execute() raises - the shape `run` receives."""

    def __init__(self, exc):
        self._exc = exc

    def execute(self):
        raise self._exc


def _use_production(monkeypatch):
    monkeypatch.setattr(main_mod, "settings", main_mod.settings.model_copy(update={"app_env": "production"}))
    assert main_mod.settings.is_production


# ---- (1) core.db ------------------------------------------------------------------------------
def test_schema_codes_set_is_exactly_the_documented_six():
    assert SCHEMA_MISSING_CODES == frozenset(ALL_CODES)
    assert SCHEMA_ERROR_DETAIL == "სერვისი დროებით მიუწვდომელია — სცადეთ მოგვიანებით."
    assert all(is_schema_missing(_api_error(c)) for c in ALL_CODES)
    assert not is_schema_missing(_api_error("23505")) and not is_schema_missing(RuntimeError("x"))


@pytest.mark.parametrize("code", ALL_CODES)
def test_run_reraises_schema_errors_as_the_original_api_error(code):
    err = _api_error(code, "Could not find the table")
    with pytest.raises(APIError) as caught:
        run(_Failing(err))
    assert caught.value is err  # not a 400 HTTPException


def test_run_still_translates_validation_errors_to_400():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        run(_Failing(_api_error("23505", "duplicate key")))
    assert caught.value.status_code == 400 and caught.value.detail == "duplicate key"


# ---- (2) main.py handler ----------------------------------------------------------------------
@pytest.mark.parametrize("code", ALL_CODES)
def test_schema_error_is_503_with_one_text_and_logged(client, user_db, caplog, code):
    user_db.errors[("shops", "select")] = _api_error(code)
    with caplog.at_level(logging.ERROR, logger="app"):
        r = client.get("/shops/me")
    assert r.status_code == 503
    assert r.json() == {"detail": SCHEMA_ERROR_DETAIL}
    errors = [x.getMessage() for x in caplog.records if x.levelno == logging.ERROR]
    assert any(code in m and "/shops/me" in m and "GET" in m for m in errors), errors


def test_schema_error_text_is_the_same_in_production(client, user_db, monkeypatch, caplog):
    _use_production(monkeypatch)
    user_db.errors[("shops", "select")] = _api_error("PGRST205", "secret schema detail")
    with caplog.at_level(logging.ERROR, logger="app"):
        r = client.get("/shops/me")
    assert r.status_code == 503
    assert r.json() == {"detail": SCHEMA_ERROR_DETAIL}
    assert "secret schema detail" not in r.text
    assert "secret schema detail" not in caplog.text  # the DB message is not logged either


# ---- (3) other APIError: unchanged 500 ---------------------------------------------------------
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


def test_non_schema_api_error_on_raw_execute_stays_500(admin_db, monkeypatch):
    _use_production(monkeypatch)
    admin_db.rpc_errors["admin_overview_stats"] = _api_error("XX000", "internal secret")
    r = TestClient(fastapi_app, raise_server_exceptions=False).get("/admin/overview")
    assert r.status_code == 500
    assert r.json() == {"detail": "სერვერის შიდა შეცდომა"}
    assert "internal secret" not in r.text


# ---- (4) the route template in the log, never the real path -------------------------------------
def test_log_has_the_route_template_not_the_psid(client, user_db, caplog):
    user_db.errors[("shops", "select")] = _api_error("42P01")
    with caplog.at_level(logging.DEBUG, logger="app"):
        r = client.delete(f"/shops/{SHOP}/customers/{PSID}")
    assert r.status_code == 503
    text = "\n".join(x.getMessage() for x in caplog.records)
    assert "/shops/{shop_id}/customers/{psid}" in text
    assert PSID not in caplog.text and SHOP not in caplog.text
    assert PSID not in r.text


def test_unrouted_scope_logs_a_question_mark(caplog):
    """No matched route in the scope (e.g. an error raised in a middleware) -> '?', never the real path."""
    import asyncio

    request = SimpleNamespace(method="GET", scope={}, url=SimpleNamespace(path=f"/x/{PSID}"))
    with caplog.at_level(logging.ERROR, logger="app"):
        resp = asyncio.run(main_mod.api_error_handler(request, _api_error("PGRST202")))
    assert resp.status_code == 503
    assert "GET ?" in caplog.text and PSID not in caplog.text


# ---- (5) products: the limit lookup fails -> 503, nothing created -------------------------------
def test_product_limit_lookup_schema_error_is_503_and_nothing_is_inserted(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"id": SHOP, "subscription_tier": "free"}]
    user_db.errors[("products", "select")] = _api_error("42703", "column does not exist")
    r = client.post("/products", json={"shop_id": SHOP, "name": "x", "price": 1, "quantity": 1})
    assert r.status_code == 503
    assert r.json() == {"detail": LIMIT_DETAIL}
    assert service_db.calls_for("products", "insert") == []


def test_product_limit_lookup_missing_column_on_tier_is_503_too(client, user_db, service_db):
    """The old "does not exist" / "Could not find" escape hatch is gone: any APIError fails closed."""
    user_db.responses[("shops", "select")] = [{"id": SHOP, "subscription_tier": "free"}]
    user_db.errors[("products", "select")] = _api_error("XX000", "Could not find the 'x' column")
    r = client.post("/products", json={"shop_id": SHOP, "name": "x", "price": 1, "quantity": 1})
    assert r.status_code == 503 and r.json() == {"detail": LIMIT_DETAIL}
    assert service_db.calls_for("products", "insert") == []


# ---- (6) orders: the idempotency lookup fails -> 503, nothing created ---------------------------
def test_order_idempotency_lookup_schema_error_is_503_and_no_order(client, service_db):
    service_db.responses[("shops", "select")] = [{"id": SHOP}]
    service_db.responses[("products", "select")] = [{"id": PRODUCT, "name": "P", "price": 5, "quantity": 100}]
    service_db.responses[("orders", "insert")] = [{"id": ORDER}]
    service_db.errors[("orders", "select")] = _api_error("42703", "column orders.idempotency_key does not exist")
    body = {
        "shop_id": SHOP, "customer_name": "Buyer", "customer_phone": "+995 555 12-34-56",
        "items": [{"product_id": PRODUCT, "name": "x", "quantity": 2}],
        "form_ms": 5000, "idempotency_key": KEY,
    }
    r = client.post("/orders", json=body)
    assert r.status_code == 503
    assert r.json() == {"detail": SCHEMA_ERROR_DETAIL}
    assert service_db.calls_for("orders", "insert") == []


# ---- (7) facebook connect: one save attempt -> save_failed --------------------------------------
@pytest.fixture
def fake_graph(monkeypatch):
    fb = fb_api.fb
    monkeypatch.setattr(fb, "verify_state", lambda s: {"shop_id": SHOP, "user_id": USER_ID})
    monkeypatch.setattr(fb, "exchange_code_for_token", lambda code: "short-token")
    monkeypatch.setattr(fb, "exchange_for_long_lived", lambda t: "long-token")
    monkeypatch.setattr(
        fb, "get_user_pages", lambda t: [{"id": "page-1", "access_token": "page-token", "name": "My Page"}]
    )
    monkeypatch.setattr(fb, "subscribe_page", lambda page_id, token: None)
    monkeypatch.setattr(fb, "get_page_instagram_account", lambda page_id, token: "ig-1")
    monkeypatch.setattr(fb, "get_user_id", lambda t: "fb-user-1")
    monkeypatch.setattr(fb_api, "encrypt", lambda v: "enc:" + v)


def test_connect_save_error_is_save_failed_after_exactly_one_attempt(client, service_db, fake_graph, caplog):
    service_db.responses[("shops", "select")] = [
        {"id": SHOP, "subscription_tier": "free", "bot_enabled": False},
    ]
    service_db.errors[("shops", "update")] = RuntimeError("db down")
    with caplog.at_level(logging.ERROR, logger="app"):
        res = client.get("/facebook/connect/callback", params={"code": "c", "state": "s"})
    assert res.status_code == 200
    assert '"reason": "save_failed"' in res.text
    updates = service_db.calls_for("shops", "update")
    assert len(updates) == 1  # no second attempt without instagram_account_id / facebook_user_id
    assert "instagram_account_id" in updates[0].payload and "facebook_user_id" in updates[0].payload
    assert any("გვერდის შენახვა ჩავარდა" in x.getMessage() for x in caplog.records)


def test_connect_duplicate_page_is_still_page_taken(client, service_db, fake_graph):
    service_db.responses[("shops", "select")] = [
        {"id": SHOP, "subscription_tier": "free", "bot_enabled": False},
    ]
    service_db.errors[("shops", "update")] = RuntimeError("duplicate key value violates unique constraint (23505)")
    res = client.get("/facebook/connect/callback", params={"code": "c", "state": "s"})
    assert '"reason": "page_taken"' in res.text
    assert len(service_db.calls_for("shops", "update")) == 1


# ---- (8) vision: no global switch-off -----------------------------------------------------------
def test_save_image_description_warns_and_retries_the_query_every_time(caplog):
    db = FakeSupabase()
    db.errors[("products", "update")] = _api_error("42703", 'column "image_description" does not exist')
    url = "https://proj.supabase.co/storage/v1/object/public/product-images/x/a.png"
    with caplog.at_level(logging.WARNING, logger="app"):
        for _ in range(2):
            assert vision.save_image_description(db, str(uuid.uuid4()), SHOP, url, "EN: a") is False
    assert len(db.calls_for("products", "update")) == 2
    warnings = [x for x in caplog.records if x.levelno == logging.WARNING and "save failed" in x.getMessage()]
    assert len(warnings) == 2
    assert hasattr(vision, "descriptions_enabled") is False
    assert not hasattr(vision, "_column_missing")


# ---- the removed fallbacks no longer exist in the source ----------------------------------------
def test_removed_fallback_markers_are_gone_from_the_touched_modules():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for rel in ("app/api/products.py", "app/api/orders.py", "app/api/facebook.py", "app/services/vision.py",
                "scripts/backfill_image_descriptions.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert not re.search(r"_MIGRATION_MISSING|_column_missing|descriptions_enabled", text), rel
