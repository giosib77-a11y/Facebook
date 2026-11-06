"""Stage 23 (A-049): behaviour tests for the paths of `api/admin.py` the other admin tests leave uncovered
(coverage gate >= 85% per file in CI). Offline (FakeSupabase); the admin dependency is overridden."""
import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.admin as admin_mod
import app.core.ratelimit as ratelimit_mod
from app.api.admin import (
    _all_auth_users,
    _apply_bot_limit,
    _email_map,
    _parse_ts,
    _restore_bots,
    get_current_admin,
)
from app.config import Settings
from app.core.security import CurrentAuth, get_current_auth
from app.main import app as fastapi_app
from tests.conftest import FakeQuery, FakeSupabase

OWNER = "11111111-1111-1111-1111-111111111111"
ADMIN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SHOP = "aaaaaaaa-0000-0000-0000-000000000001"
SHOP_B = "bbbbbbbb-0000-0000-0000-00000000000b"


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


def _users(*ids_emails):
    return [SimpleNamespace(id=i, email=e) for i, e in ids_emails]


def _auth_admin(db, list_users):
    db.auth = SimpleNamespace(admin=SimpleNamespace(list_users=list_users))


def _shop(sid, created, *, enabled, page="p", tier="free"):
    return {
        "id": sid, "owner_id": OWNER, "name": sid, "created_at": created,
        "bot_enabled": enabled, "facebook_page_id": page, "subscription_tier": tier,
    }


# ---- get_current_admin: empty ADMIN_USER_IDS in production --------------------------------------
def test_production_with_empty_admin_ids_warns_once_and_forbids_everyone(monkeypatch, user_db, caplog):
    monkeypatch.setattr(admin_mod, "_warned_no_admins", False)
    settings = Settings(admin_user_ids="", app_env="production", admin_require_mfa=False)
    monkeypatch.setattr(admin_mod, "get_settings", lambda: settings)
    fastapi_app.dependency_overrides[get_current_auth] = lambda: CurrentAuth(
        user_id=ADMIN_ID, email=None, client=user_db
    )
    try:
        with caplog.at_level(logging.WARNING, logger="app"):
            assert TestClient(fastapi_app).get("/admin/check").status_code == 403
            assert TestClient(fastapi_app).get("/admin/check").status_code == 403
    finally:
        fastapi_app.dependency_overrides.clear()
    warned = [r for r in caplog.records if "ADMIN_USER_IDS is empty in production" in r.getMessage()]
    assert len(warned) == 1
    assert ADMIN_ID not in caplog.text


# ---- GET /admin/client-ip -----------------------------------------------------------------------
def test_client_ip_reports_headers_and_trusted_resolved_ip(admin_db, monkeypatch):
    settings = Settings(app_env="development", client_ip_trusted_hops=2)
    monkeypatch.setattr(admin_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(ratelimit_mod, "get_settings", lambda: settings)

    r = TestClient(fastapi_app).get(
        "/admin/client-ip",
        headers={
            "x-forwarded-for": "9.9.9.9, 1.1.1.1, 2.2.2.2",
            "cf-connecting-ip": "3.3.3.3",
            "true-client-ip": "4.4.4.4",
            "x-real-ip": "5.5.5.5",
        },
    )

    assert r.status_code == 200, r.text
    assert r.json() == {
        "x_forwarded_for": "9.9.9.9, 1.1.1.1, 2.2.2.2",
        "cf_connecting_ip": "3.3.3.3",
        "true_client_ip": "4.4.4.4",
        "x_real_ip": "5.5.5.5",
        "peer_untrusted": "testclient",
        # 2 trusted hops -> second entry from the right; the client-supplied CF header is ignored
        "resolved": "1.1.1.1",
        "client_ip_trusted_hops": 2,
    }


def test_client_ip_without_headers_has_null_fields(admin_db, monkeypatch):
    settings = Settings(app_env="development", client_ip_trusted_hops=1)
    monkeypatch.setattr(admin_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(ratelimit_mod, "get_settings", lambda: settings)

    body = TestClient(fastapi_app).get("/admin/client-ip").json()

    assert body["x_forwarded_for"] is None and body["cf_connecting_ip"] is None
    assert body["resolved"] == "testclient"  # development: socket peer


def test_client_ip_requires_admin(client):
    assert client.get("/admin/client-ip").status_code in (401, 403)


# ---- _parse_ts ----------------------------------------------------------------------------------
def test_parse_ts_accepts_z_suffix_and_returns_none_for_garbage():
    ts = _parse_ts("2026-01-05T10:00:00Z")
    assert ts is not None and ts.utcoffset().total_seconds() == 0 and ts.year == 2026
    for bad in ("not-a-date", "", None, 12345678901234567890):
        assert _parse_ts(bad) is None


def test_overview_python_ignores_unparseable_order_dates(admin_db):
    admin_db.responses[("orders", "select")] = [
        {"id": "1", "total": 10, "status": "new", "created_at": "garbage"},
        {"id": "2", "total": 5, "status": "new", "created_at": None},
    ]
    admin_db.counts[("products", "select")] = 0

    stats = admin_mod._overview_python(admin_db)

    assert stats["total_orders"] == 2 and stats["orders_30d"] == 0
    assert stats["revenue"] == 15.0


# ---- _all_auth_users / _email_map ---------------------------------------------------------------
def test_all_auth_users_reads_pages_until_an_empty_one(admin_db):
    pages = {1: _users(("u1", "a@x"), ("u2", "b@x")), 2: _users(("u3", "c@x")), 3: []}
    seen = []

    def list_users(page=1, per_page=0):
        seen.append((page, per_page))
        return pages[page]

    _auth_admin(admin_db, list_users)

    assert [u.id for u in _all_auth_users(admin_db)] == ["u1", "u2", "u3"]
    # a short page (< per_page) does not stop the loop: the server may silently cap per_page
    assert seen == [(1, 200), (2, 200), (3, 200)]


def test_all_auth_users_accepts_response_object_with_users_attr(admin_db):
    _auth_admin(
        admin_db,
        lambda page=1, per_page=0: SimpleNamespace(users=_users(("u1", "a@x")) if page == 1 else []),
    )
    assert [u.id for u in _all_auth_users(admin_db)] == ["u1"]


def test_all_auth_users_is_capped_at_50_pages(admin_db):
    calls = []

    def list_users(page=1, per_page=0):
        calls.append(page)
        return _users((f"u{page}", None))

    _auth_admin(admin_db, list_users)

    assert len(_all_auth_users(admin_db)) == 50
    assert calls == list(range(1, 51))


def test_all_auth_users_old_gotrue_without_paging_args_uses_single_call(admin_db):
    calls = []

    def list_users(*args, **kwargs):
        calls.append((args, kwargs))
        if kwargs:
            raise TypeError("list_users() got an unexpected keyword argument 'page'")
        return _users(("u1", "a@x"), ("u2", "b@x"))

    _auth_admin(admin_db, list_users)

    assert [u.id for u in _all_auth_users(admin_db)] == ["u1", "u2"]
    assert calls[-1] == ((), {})  # one plain call, then stop (no endless paging)
    assert len(calls) == 2


def test_all_auth_users_old_gotrue_failing_plain_call_returns_empty(admin_db):
    def list_users(*args, **kwargs):
        if kwargs:
            raise TypeError("no paging")
        raise RuntimeError("auth down")

    _auth_admin(admin_db, list_users)

    assert _all_auth_users(admin_db) == []


def test_all_auth_users_error_stops_and_keeps_what_was_read(admin_db):
    def list_users(page=1, per_page=0):
        if page == 2:
            raise RuntimeError("auth down")
        return _users(("u1", "a@x"))

    _auth_admin(admin_db, list_users)

    assert [u.id for u in _all_auth_users(admin_db)] == ["u1"]


def test_all_auth_users_first_page_error_is_empty_not_500(admin_db):
    def list_users(page=1, per_page=0):
        raise RuntimeError("auth down")

    _auth_admin(admin_db, list_users)

    assert _all_auth_users(admin_db) == []


def test_email_map_maps_id_to_email_and_skips_users_without_id(admin_db):
    users = [
        SimpleNamespace(id="u1", email="a@x"),
        SimpleNamespace(id=None, email="ghost@x"),
        SimpleNamespace(id="", email="blank@x"),
        SimpleNamespace(id="u2"),  # no email attribute at all
    ]
    _auth_admin(admin_db, lambda page=1, per_page=0: users if page == 1 else [])

    assert _email_map(admin_db) == {"u1": "a@x", "u2": None}


# ---- GET /admin/sellers -------------------------------------------------------------------------
def test_all_sellers_confirmed_flag_and_shop_counts(admin_db):
    admin_db.responses[("shops", "select")] = [{"owner_id": "u1"}, {"owner_id": "u1"}, {"owner_id": "u2"}]
    users = [
        SimpleNamespace(id="u1", email="a@x", email_confirmed_at="2026-01-01", last_sign_in_at="t", created_at="c"),
        SimpleNamespace(id="u2", email="b@x", confirmed_at="2026-01-02"),  # older field name
        SimpleNamespace(id="u3", email="c@x"),  # not confirmed, no shops
    ]
    _auth_admin(admin_db, lambda page=1, per_page=0: users if page == 1 else [])

    r = TestClient(fastapi_app).get("/admin/sellers")

    assert r.status_code == 200, r.text
    by_id = {x["id"]: x for x in r.json()}
    assert [by_id[k]["shops"] for k in ("u1", "u2", "u3")] == [2, 1, 0]
    assert [by_id[k]["confirmed"] for k in ("u1", "u2", "u3")] == [True, True, False]
    assert by_id["u1"]["last_sign_in"] == "t" and by_id["u3"]["last_sign_in"] is None


# ---- GET /admin/shops: bot_customers table missing (Python fallback) ----------------------------
def test_admin_shops_fallback_without_bot_customers_table_shows_zero(admin_db, monkeypatch):
    monkeypatch.setattr(admin_mod, "_RPC_WARNED", set())

    class NoFn(Exception):
        code = "PGRST202"

    admin_db.rpc_errors["admin_shop_counts"] = NoFn("missing")
    admin_db.errors[("bot_customers", "select")] = RuntimeError("relation does not exist")
    admin_db.responses[("shops", "select")] = [_shop(SHOP, "2026-01-01", enabled=True)]
    admin_db.responses[("products", "select")] = [{"shop_id": SHOP}, {"shop_id": SHOP}]
    admin_db.responses[("orders", "select")] = [{"shop_id": SHOP}]
    _auth_admin(admin_db, lambda page=1, per_page=0: [])

    r = TestClient(fastapi_app).get("/admin/shops")

    assert r.status_code == 200, r.text
    (row,) = r.json()
    assert (row["products"], row["orders"], row["monthly_customers"]) == (2, 1, 0)


# ---- GET /admin/orders: limit clamp -------------------------------------------------------------
@pytest.mark.parametrize("asked,used", [(0, 1), (-5, 1), (1, 1), (50, 50), (200, 200), (1000, 200)])
def test_recent_orders_limit_is_clamped_to_1_200(admin_db, monkeypatch, asked, used):
    limits = []
    monkeypatch.setattr(FakeQuery, "limit", lambda self, n: (limits.append(n), self)[1])
    admin_db.responses[("orders", "select")] = []

    r = TestClient(fastapi_app).get(f"/admin/orders?limit={asked}")

    assert r.status_code == 200 and r.json() == []
    assert limits == [used]


def test_recent_orders_unknown_shop_gets_null_name(admin_db):
    admin_db.responses[("orders", "select")] = [{"id": "1", "shop_id": SHOP}]
    admin_db.responses[("shops", "select")] = []

    assert TestClient(fastapi_app).get("/admin/orders").json()[0]["shop_name"] is None


# ---- GET /admin/shops/{id} ----------------------------------------------------------------------
def test_shop_detail_unknown_shop_is_404_and_loads_nothing_else(admin_db):
    admin_db.responses[("shops", "select")] = []

    r = TestClient(fastapi_app).get(f"/admin/shops/{SHOP}")

    assert r.status_code == 404
    assert admin_db.calls_for("products", "select") == [] and admin_db.calls_for("orders", "select") == []


def test_shop_detail_hides_token_and_knowledge_and_limits_orders(admin_db):
    admin_db.responses[("shops", "select")] = [
        {"id": SHOP, "name": "A", "facebook_page_token": "enc-token", "knowledge": "private text"}
    ]
    admin_db.responses[("orders", "select")] = [{"id": "o1", "shop_id": SHOP}]

    r = TestClient(fastapi_app).get(f"/admin/shops/{SHOP}")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["shop"] == {"id": SHOP, "name": "A"}
    assert "enc-token" not in r.text and "private text" not in r.text
    assert body["orders"] == [{"id": "o1", "shop_id": SHOP}]


# ---- PATCH /admin/shops/{id} --------------------------------------------------------------------
def _patch(body, shop=SHOP):
    return TestClient(fastapi_app).patch(f"/admin/shops/{shop}", json=body)


def test_update_shop_without_fields_is_400_and_writes_nothing(admin_db):
    r = _patch({})

    assert r.status_code == 400
    assert admin_db.calls == []


def test_update_shop_unknown_tier_is_400_and_writes_nothing(admin_db):
    r = _patch({"subscription_tier": "platinum"})

    assert r.status_code == 400
    assert admin_db.calls_for("shops", "update") == []


def test_update_shop_unknown_shop_is_404_and_writes_nothing(admin_db):
    admin_db.responses[("shops", "select")] = []

    r = _patch({"bot_enabled": False})

    assert r.status_code == 404
    assert admin_db.calls_for("shops", "update") == []
    assert admin_db.calls_for("admin_audit_log", "insert") == []


def test_update_shop_bot_toggle_touches_only_that_shop_and_strips_secrets(admin_db):
    admin_db.responses[("shops", "select")] = [
        {"id": SHOP, "owner_id": OWNER, "bot_enabled": False, "facebook_page_token": "enc", "knowledge": "k"}
    ]

    r = _patch({"bot_enabled": False})

    assert r.status_code == 200, r.text
    assert r.json() == {"id": SHOP, "owner_id": OWNER, "bot_enabled": False}
    (upd,) = admin_db.calls_for("shops", "update")
    assert upd.payload == {"bot_enabled": False} and ("eq", "id", SHOP) in upd.filters
    assert admin_db.calls_for("subscriptions", "upsert") == []
    (audit,) = admin_db.calls_for("admin_audit_log", "insert")
    assert audit.payload["action"] == "shop.update" and audit.payload["target"] == SHOP


def test_update_shop_tier_for_shop_without_owner_updates_only_that_shop(admin_db):
    admin_db.responses[("shops", "select")] = [{"id": SHOP, "owner_id": None}]

    r = _patch({"subscription_tier": "basic"})

    assert r.status_code == 200, r.text
    (upd,) = admin_db.calls_for("shops", "update")
    assert upd.payload == {"subscription_tier": "basic"}
    assert upd.filters == [("eq", "id", SHOP)]
    assert admin_db.calls_for("subscriptions", "upsert") == []


def test_update_shop_bot_limit_failure_is_500_with_retry_message_and_no_exception_text(
    admin_db, monkeypatch, caplog
):
    admin_db.responses[("shops", "select")] = [{"id": SHOP, "owner_id": OWNER}]

    def boom(sc, owner_id):
        raise RuntimeError("secret-db-detail")

    monkeypatch.setattr(admin_mod, "enforce_bot_limit", boom)

    with caplog.at_level(logging.ERROR, logger="app"):
        r = _patch({"subscription_tier": "basic"})

    assert r.status_code == 500
    assert "გაიმეორე მოქმედება" in r.json()["detail"]
    assert "secret-db-detail" not in r.text
    assert any(rec.levelno == logging.ERROR for rec in caplog.records)  # logged for the operator
    # tier already changed (documented: admin repeats the action) - audit is not written for a failed request
    assert admin_db.calls_for("admin_audit_log", "insert") == []


# ---- _apply_bot_limit / _restore_bots -----------------------------------------------------------
def test_apply_bot_limit_downgrade_disables_the_newest_enabled_shop(admin_db):
    admin_db.responses[("shops", "select")] = [
        _shop(SHOP, "2026-01-01", enabled=True), _shop(SHOP_B, "2026-02-01", enabled=True),
    ]

    _apply_bot_limit(admin_db, OWNER, "free")

    (upd,) = admin_db.calls_for("shops", "update")
    assert upd.payload == {"bot_enabled": False}
    assert ("in", "id", [SHOP_B]) in upd.filters and ("eq", "owner_id", OWNER) in upd.filters


def test_restore_bots_standard_fills_only_free_slots_oldest_first(admin_db):
    admin_db.responses[("shops", "select")] = [
        _shop("s-on", "2026-03-01", enabled=True, tier="standard"),
        _shop("s-new", "2026-02-01", enabled=False, tier="standard"),
        _shop("s-old", "2026-01-01", enabled=False, tier="standard"),
    ]

    restored = _restore_bots(admin_db, OWNER, "standard")  # limit 2, one already on -> one slot

    assert restored == 1
    (upd,) = admin_db.calls_for("shops", "update")
    assert upd.payload == {"bot_enabled": True} and ("in", "id", ["s-old"]) in upd.filters


def test_restore_bots_unlimited_tier_restores_all_connected_but_skips_unconnected(admin_db):
    admin_db.responses[("shops", "select")] = [
        _shop("s1", "2026-01-01", enabled=False, tier="business"),
        _shop("s2", "2026-01-02", enabled=False, tier="business"),
        _shop("s3", "2026-01-03", enabled=False, page=None, tier="business"),  # no FB page: stays off
        _shop("s4", "2026-01-04", enabled=True, tier="business"),
    ]

    assert _restore_bots(admin_db, OWNER, "business") == 2
    (upd,) = admin_db.calls_for("shops", "update")
    assert ("in", "id", ["s1", "s2"]) in upd.filters


def test_restore_bots_no_free_slot_changes_nothing(admin_db):
    admin_db.responses[("shops", "select")] = [
        _shop("s-on", "2026-01-01", enabled=True), _shop("s-off", "2026-01-02", enabled=False),
    ]

    assert _restore_bots(admin_db, OWNER, "free") == 0  # limit 1, already used
    assert admin_db.calls_for("shops", "update") == []


def test_restore_bots_nothing_to_restore_returns_zero_without_writes(admin_db):
    admin_db.responses[("shops", "select")] = [_shop("s1", "2026-01-01", enabled=True)]
    assert _restore_bots(admin_db, OWNER, "business") == 0

    admin_db.responses[("shops", "select")] = []
    assert _restore_bots(admin_db, OWNER, "business") == 0
    assert admin_db.calls_for("shops", "update") == []


def test_restore_bots_unknown_tier_is_treated_as_free(admin_db):
    admin_db.responses[("shops", "select")] = [
        _shop("s1", "2026-01-01", enabled=False), _shop("s2", "2026-01-02", enabled=False),
    ]

    assert _restore_bots(admin_db, OWNER, "nonsense") == 1  # free limit is 1


# ---- DELETE /admin/shops/{id}: storage cleanup --------------------------------------------------
def test_remove_shop_images_deletes_in_batches_until_folder_is_empty():
    removed = []
    batches = [[{"name": "a.jpg"}, {"name": "b.jpg"}, {"name": None}], [{"name": "c.jpg"}], []]

    class Bucket:
        def list(self, path, options):
            return batches.pop(0)

        def remove(self, paths):
            removed.append(paths)

    sc = SimpleNamespace(storage=SimpleNamespace(from_=lambda name: Bucket()))

    admin_mod._remove_shop_images(sc, SHOP)

    assert removed == [[f"{SHOP}/a.jpg", f"{SHOP}/b.jpg"], [f"{SHOP}/c.jpg"]]


def test_delete_shop_storage_error_is_warning_without_exception_text_and_still_204(admin_db, caplog):
    admin_db.responses[("shops", "select")] = [{"id": SHOP, "owner_id": OWNER}]

    class Boom:
        def from_(self, name):
            raise RuntimeError("storage-secret-detail")

    admin_db.storage = Boom()

    with caplog.at_level(logging.WARNING, logger="app"):
        r = TestClient(fastapi_app).delete(f"/admin/shops/{SHOP}")

    assert r.status_code == 204
    assert [x for x in caplog.records if x.levelno == logging.WARNING and "image cleanup failed" in x.getMessage()]
    assert "storage-secret-detail" not in caplog.text
    assert len(admin_db.calls_for("shops", "delete")) == 1


# ---- GET /admin/upgrade-requests ----------------------------------------------------------------
def test_upgrade_requests_missing_table_returns_empty_list(admin_db):
    admin_db.errors[("upgrade_requests", "select")] = RuntimeError("relation does not exist")

    r = TestClient(fastapi_app).get("/admin/upgrade-requests")

    assert r.status_code == 200 and r.json() == []
    assert admin_db.calls_for("shops", "select") == []


def test_upgrade_requests_enriched_with_owner_email_and_unknown_tier_label(admin_db):
    admin_db.responses[("upgrade_requests", "select")] = [
        {"id": "r1", "shop_id": SHOP, "requested_tier": "standard", "status": "pending"},
        {"id": "r2", "shop_id": "gone", "requested_tier": "weird", "status": "pending"},
    ]
    admin_db.responses[("shops", "select")] = [
        {"id": SHOP, "name": "A", "subscription_tier": None, "owner_id": OWNER}
    ]
    _auth_admin(admin_db, lambda page=1, per_page=0: _users((OWNER, "o@test.local")) if page == 1 else [])

    r = TestClient(fastapi_app).get("/admin/upgrade-requests")

    assert r.status_code == 200, r.text
    first, second = r.json()
    assert (first["owner_email"], first["current_tier"], first["shop_name"]) == ("o@test.local", "free", "A")
    assert second["shop_name"] is None and second["owner_email"] is None
    assert second["tier_label"] == "weird"  # unknown tier: raw value, not a 500


# ---- POST /admin/upgrade-requests/{id}/resolve --------------------------------------------------
def _resolve(approve, req_id="r1"):
    return TestClient(fastapi_app).post(f"/admin/upgrade-requests/{req_id}/resolve", json={"approve": approve})


def test_approve_for_shop_without_owner_row_upgrades_only_that_shop(admin_db):
    admin_db.responses[("upgrade_requests", "select")] = [
        {"id": "r1", "shop_id": SHOP, "requested_tier": "standard", "status": "pending"}
    ]
    admin_db.responses[("shops", "select")] = []  # shop vanished -> no owner to resolve

    r = _resolve(True)

    assert r.status_code == 200, r.text
    (shop_upd, ) = admin_db.calls_for("shops", "update")
    assert shop_upd.payload == {"subscription_tier": "standard"} and shop_upd.filters == [("eq", "id", SHOP)]
    assert admin_db.calls_for("subscriptions", "upsert") == []
    (req_upd,) = admin_db.calls_for("upgrade_requests", "update")
    assert req_upd.payload["status"] == "approved" and ("eq", "status", "pending") in req_upd.filters
    (audit,) = admin_db.calls_for("admin_audit_log", "insert")
    assert audit.payload["action"] == "upgrade_request.approve" and audit.payload["target"] == "r1"


def test_reject_audits_the_rejection_and_never_changes_the_tier(admin_db):
    admin_db.responses[("upgrade_requests", "select")] = [
        {"id": "r1", "shop_id": SHOP, "requested_tier": "standard", "status": "pending"}
    ]

    r = _resolve(False)

    assert r.status_code == 200 and r.json() == {"ok": True}
    assert admin_db.calls_for("shops", "update") == []
    (audit,) = admin_db.calls_for("admin_audit_log", "insert")
    assert audit.payload["action"] == "upgrade_request.reject"
    (req_upd,) = admin_db.calls_for("upgrade_requests", "update")
    assert req_upd.payload["status"] == "rejected"


def test_resolve_body_must_contain_approve_flag(admin_db):
    r = TestClient(fastapi_app).post("/admin/upgrade-requests/r1/resolve", json={})

    assert r.status_code == 422
    assert admin_db.calls == []


# ---- POST /admin/subscriptions/{owner}/extend: audit --------------------------------------------
def test_extend_writes_audit_row_with_tier_and_days(admin_db):
    admin_db.responses[("shops", "select")] = [{"subscription_tier": "basic"}]

    r = TestClient(fastapi_app).post(f"/admin/subscriptions/{OWNER}/extend", json={"days": 7})

    assert r.status_code == 200, r.text
    (audit,) = admin_db.calls_for("admin_audit_log", "insert")
    assert audit.payload["action"] == "subscription.extend" and audit.payload["target"] == OWNER
    assert audit.payload["details"]["tier"] == "basic" and audit.payload["details"]["days"] == 7
