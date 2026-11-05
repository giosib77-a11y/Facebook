"""S22-4 (A-041 / N-04): admin overview / growth / shops from SQL aggregation (migration 0039) with a paginated
Python fallback; the other admin lists use fetch_all / in_. Offline (FakeSupabase, 1000-row cap, `range`)."""
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.admin as admin_mod
from app.api.admin import _last_months, get_current_admin
from app.core.security import CurrentAuth
from app.core.tiers import TIER_PRICES
from app.main import app as fastapi_app
from tests.conftest import FakeSupabase

SHOP_A = "aaaaaaaa-0000-0000-0000-00000000000a"
SHOP_B = "bbbbbbbb-0000-0000-0000-00000000000b"
OWNER = "11111111-1111-1111-1111-111111111111"
NOW_ISO = datetime.now(timezone.utc).isoformat()
THIS_MONTH = datetime.now(timezone.utc).strftime("%Y-%m")
MISSING_LOG = "missing (migration 0039 not applied)"


class RpcError(Exception):
    def __init__(self, code):
        super().__init__(f"rpc error {code}")
        self.code = code


@pytest.fixture(autouse=True)
def _fresh_warning_flags(monkeypatch):
    monkeypatch.setattr(admin_mod, "_RPC_WARNED", set())


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


def _get(path, **kw):
    return TestClient(fastapi_app, **kw).get(path)


def _rpc_calls(db, fn):
    return [c for c in db.rpc_calls if c.fn == fn]


def _missing_warnings(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING and MISSING_LOG in r.getMessage()]


def _orders(n, **extra):
    return [{"id": f"o{i}", "shop_id": SHOP_A, "total": 1, "status": "new", "created_at": NOW_ISO, **extra}
            for i in range(n)]


def _overview_stats(**over):
    stats = {
        "total_shops": 3, "total_sellers": 3, "connected_shops": 2, "total_products": 7,
        "total_orders": 2500, "orders_30d": 40, "revenue": 12345.5,
        "owner_tiers": {"basic": 2, "business": 1},
    }
    stats.update(over)
    return stats


# ---- overview ---------------------------------------------------------------
def test_overview_uses_sql_aggregation(admin_db):
    admin_db.rpc_responses["admin_overview_stats"] = _overview_stats()

    r = _get("/admin/overview")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_orders"] == 2500
    assert body["revenue"] == 12345.5
    assert body["orders_30d"] == 40
    assert body["total_shops"] == 3 and body["total_sellers"] == 3
    assert body["connected_shops"] == 2 and body["total_products"] == 7
    assert body["mrr"] == 2 * TIER_PRICES["basic"] + TIER_PRICES["business"]
    assert body["tier_counts"] == {"free": 0, "basic": 2, "standard": 0, "business": 1}
    assert set(body) == {
        "total_shops", "total_sellers", "connected_shops", "total_products", "total_orders",
        "orders_30d", "revenue", "mrr", "tier_counts", "llm",
    }
    # no Python aggregation when the RPC answered
    assert admin_db.calls_for("orders", "select") == []
    assert admin_db.calls_for("shops", "select") == []
    assert admin_db.calls_for("products", "select") == []


def test_overview_sql_unknown_tier_counts_as_free(admin_db):
    admin_db.rpc_responses["admin_overview_stats"] = _overview_stats(owner_tiers={"weird": 2, "free": 1})

    body = _get("/admin/overview").json()

    assert body["tier_counts"]["free"] == 3
    assert body["mrr"] == 3 * TIER_PRICES["free"]


def test_overview_sql_empty_owner_tiers(admin_db):
    admin_db.rpc_responses["admin_overview_stats"] = _overview_stats(owner_tiers={}, revenue=0, total_orders=0)

    body = _get("/admin/overview").json()

    assert body["tier_counts"] == {"free": 0, "basic": 0, "standard": 0, "business": 0}
    assert body["mrr"] == 0 and body["revenue"] == 0


@pytest.mark.parametrize("code", ["PGRST202", "42883"])
def test_overview_python_fallback_without_0039(admin_db, caplog, code):
    admin_db.rpc_errors["admin_overview_stats"] = RpcError(code)
    admin_db.responses[("orders", "select")] = _orders(2500)
    admin_db.counts[("products", "select")] = 9
    admin_db.responses[("shops", "select")] = [
        {"id": SHOP_A, "owner_id": OWNER, "facebook_page_id": "p1", "subscription_tier": "basic"},
        {"id": SHOP_B, "owner_id": OWNER, "facebook_page_id": None, "subscription_tier": "standard"},
        {"id": "c", "owner_id": "22222222-2222-2222-2222-222222222222", "facebook_page_id": "p3",
         "subscription_tier": None},
    ]
    caplog.set_level(logging.WARNING, logger="app")

    r1 = _get("/admin/overview")
    r2 = _get("/admin/overview")

    assert r1.status_code == 200 and r2.status_code == 200, r1.text
    body = r1.json()
    assert body["total_orders"] == 2500  # past the fake's 1000-row cap -> needs pagination
    assert body["revenue"] == 2500.0
    assert body["orders_30d"] == 2500
    assert body["total_shops"] == 3 and body["total_sellers"] == 2 and body["connected_shops"] == 2
    assert body["total_products"] == 9
    assert body["tier_counts"] == {"free": 1, "basic": 0, "standard": 1, "business": 0}
    assert body["mrr"] == TIER_PRICES["standard"]
    assert r2.json() == body
    assert len(_rpc_calls(admin_db, "admin_overview_stats")) == 2  # retried every request
    assert len(_missing_warnings(caplog)) == 1  # warned once per process
    # the order pages were read with range() and ended on a unique column
    pages = admin_db.calls_for("orders", "select")
    assert [p.range_ for p in pages[:3]] == [(0, 999), (1000, 1999), (2000, 2999)]
    assert all(p.orders[-1] == ("id", False) for p in pages)


def test_overview_python_fallback_excludes_cancelled_from_revenue(admin_db):
    admin_db.rpc_errors["admin_overview_stats"] = RpcError("PGRST202")
    admin_db.responses[("orders", "select")] = [
        {"id": "1", "total": 10, "status": "new", "created_at": NOW_ISO},
        {"id": "2", "total": 5.5, "status": None, "created_at": NOW_ISO},
        {"id": "3", "total": 99, "status": "cancelled", "created_at": "2020-01-01T00:00:00+00:00"},
    ]

    body = _get("/admin/overview").json()

    assert body["total_orders"] == 3 and body["orders_30d"] == 2
    assert body["revenue"] == 15.5


def test_overview_non_dict_rpc_result_falls_back_without_warning(admin_db, caplog):
    # fake default: rpc data None -> Python path, no "missing" warning
    admin_db.responses[("orders", "select")] = _orders(3)
    caplog.set_level(logging.WARNING, logger="app")

    body = _get("/admin/overview").json()

    assert body["total_orders"] == 3
    assert _missing_warnings(caplog) == []


def test_overview_other_rpc_error_is_500(admin_db, caplog):
    admin_db.rpc_errors["admin_overview_stats"] = RpcError("XX000")
    admin_db.responses[("orders", "select")] = _orders(3)

    r = _get("/admin/overview", raise_server_exceptions=False)

    assert r.status_code == 500
    assert admin_db.calls_for("orders", "select") == []  # no silent fallback on real errors
    assert _missing_warnings(caplog) == []


def test_overview_rpc_error_without_code_is_500(admin_db):
    admin_db.rpc_errors["admin_overview_stats"] = RuntimeError("boom")

    assert _get("/admin/overview", raise_server_exceptions=False).status_code == 500


# ---- growth -----------------------------------------------------------------
def test_growth_from_rpc(admin_db):
    yms = _last_months(24)
    admin_db.rpc_responses["admin_growth"] = {
        yms[-1]: {"shops": 2, "orders": 5},
        yms[0]: {"shops": 1, "orders": 0},
        "1999-01": {"shops": 9, "orders": 9},  # outside the window -> ignored
    }

    r = _get("/admin/growth?months=99")

    assert r.status_code == 200, r.text
    (call,) = _rpc_calls(admin_db, "admin_growth")
    assert call.params == {"p_months": 24}
    rows = r.json()
    assert len(rows) == 24
    assert [x["ym"] for x in rows] == yms
    assert set(rows[0]) == {"ym", "shops", "orders"}
    assert rows[-1] == {"ym": yms[-1], "shops": 2, "orders": 5}
    assert rows[0] == {"ym": yms[0], "shops": 1, "orders": 0}
    assert rows[5] == {"ym": yms[5], "shops": 0, "orders": 0}  # zero-filled
    assert all(x["ym"] != "1999-01" for x in rows)
    assert admin_db.calls_for("orders", "select") == []
    assert admin_db.calls_for("shops", "select") == []


def test_growth_months_clamped_low(admin_db):
    admin_db.rpc_responses["admin_growth"] = {}

    rows = _get("/admin/growth?months=0").json()

    assert _rpc_calls(admin_db, "admin_growth")[0].params == {"p_months": 1}
    assert rows == [{"ym": THIS_MONTH, "shops": 0, "orders": 0}]


def test_growth_python_fallback_counts_past_1000_orders(admin_db, caplog):
    admin_db.rpc_errors["admin_growth"] = RpcError("PGRST202")
    admin_db.responses[("orders", "select")] = _orders(2500)
    admin_db.responses[("shops", "select")] = [{"id": "s1", "created_at": NOW_ISO}]
    caplog.set_level(logging.WARNING, logger="app")

    rows = _get("/admin/growth?months=3").json()

    assert len(rows) == 3
    assert rows[-1] == {"ym": THIS_MONTH, "shops": 1, "orders": 2500}
    assert rows[0]["orders"] == 0
    assert len(_missing_warnings(caplog)) == 1


# ---- /admin/shops -----------------------------------------------------------
def _shop(sid, **extra):
    return {"id": sid, "owner_id": OWNER, "name": f"n-{sid[:2]}", "created_at": NOW_ISO,
            "bot_enabled": True, "subscription_tier": "basic", "facebook_page_id": "p", **extra}


def test_admin_shops_counts_from_rpc(admin_db):
    admin_db.responses[("shops", "select")] = [_shop(SHOP_A), _shop(SHOP_B)]
    admin_db.rpc_responses["admin_shop_counts"] = {
        SHOP_A: {"products": 1500, "orders": 7, "customers": 3},
    }

    r = _get("/admin/shops")

    assert r.status_code == 200, r.text
    by_id = {s["id"]: s for s in r.json()}
    assert by_id[SHOP_A]["products"] == 1500
    assert by_id[SHOP_A]["orders"] == 7
    assert by_id[SHOP_A]["monthly_customers"] == 3
    # shop missing in the RPC result -> zeros
    assert by_id[SHOP_B]["products"] == 0 and by_id[SHOP_B]["orders"] == 0
    assert by_id[SHOP_B]["monthly_customers"] == 0
    for table in ("products", "orders", "bot_customers"):
        assert admin_db.calls_for(table, "select") == []
    assert set(by_id[SHOP_A]) == {
        "id", "name", "owner_id", "paid_until", "owner_email", "created_at", "products", "orders",
        "fb_connected", "bot_enabled", "tier", "tier_label", "monthly_customers", "customer_limit",
    }


def test_admin_shops_counts_fallback_past_1000(admin_db, caplog):
    admin_db.rpc_errors["admin_shop_counts"] = RpcError("42883")
    admin_db.responses[("shops", "select")] = [_shop(SHOP_A), _shop(SHOP_B)]
    admin_db.responses[("products", "select")] = (
        [{"shop_id": SHOP_A, "id": f"p{i}"} for i in range(1500)] + [{"shop_id": SHOP_B, "id": "pb"}]
    )
    admin_db.responses[("orders", "select")] = [{"shop_id": SHOP_B, "id": f"o{i}"} for i in range(1200)]
    admin_db.responses[("bot_customers", "select")] = [{"shop_id": SHOP_A, "psid": f"u{i}"} for i in range(4)]
    caplog.set_level(logging.WARNING, logger="app")

    by_id = {s["id"]: s for s in _get("/admin/shops").json()}

    assert by_id[SHOP_A]["products"] == 1500
    assert by_id[SHOP_B]["products"] == 1
    assert by_id[SHOP_B]["orders"] == 1200
    assert by_id[SHOP_A]["monthly_customers"] == 4
    (cust,) = admin_db.calls_for("bot_customers", "select")[:1]
    assert ("eq", "ym", THIS_MONTH) in cust.filters
    assert cust.orders == [("shop_id", False), ("psid", False)]
    assert len(_missing_warnings(caplog)) == 1


def test_admin_shops_lists_all_2500_shops(admin_db):
    admin_db.responses[("shops", "select")] = [_shop(f"s{i:05d}") for i in range(2500)]

    r = _get("/admin/shops")

    assert r.status_code == 200
    assert len(r.json()) == 2500
    pages = admin_db.calls_for("shops", "select")
    assert pages[0].orders == [("created_at", True), ("id", False)]


def test_admin_shops_subscriptions_missing_table_still_works(admin_db):
    admin_db.responses[("shops", "select")] = [_shop(SHOP_A)]
    admin_db.rpc_responses["admin_shop_counts"] = {}
    admin_db.errors[("subscriptions", "select")] = RuntimeError("relation does not exist")

    r = _get("/admin/shops")

    assert r.status_code == 200
    assert r.json()[0]["paid_until"] is None


def test_admin_shops_paid_until_from_subscriptions(admin_db):
    admin_db.responses[("shops", "select")] = [_shop(SHOP_A)]
    admin_db.rpc_responses["admin_shop_counts"] = {}
    admin_db.responses[("subscriptions", "select")] = [{"owner_id": OWNER, "paid_until": "2030-01-01T00:00:00+00:00"}]

    assert _get("/admin/shops").json()[0]["paid_until"] == "2030-01-01T00:00:00+00:00"


# ---- the other admin lists --------------------------------------------------
def test_recent_orders_loads_names_only_for_listed_shops(admin_db):
    admin_db.responses[("orders", "select")] = [
        {"id": "1", "shop_id": SHOP_B}, {"id": "2", "shop_id": SHOP_A},
        {"id": "3", "shop_id": SHOP_A}, {"id": "4", "shop_id": None},
    ]
    admin_db.responses[("shops", "select")] = [{"id": SHOP_A, "name": "A"}, {"id": SHOP_B, "name": "B"}]

    r = _get("/admin/orders")

    assert r.status_code == 200
    assert [o["shop_name"] for o in r.json()] == ["B", "A", "A", None]
    (shop_q,) = admin_db.calls_for("shops", "select")
    assert shop_q.filters == [("in", "id", sorted([SHOP_A, SHOP_B]))]


def test_recent_orders_without_orders_does_not_query_shops(admin_db):
    admin_db.responses[("orders", "select")] = []

    r = _get("/admin/orders")

    assert r.status_code == 200 and r.json() == []
    assert admin_db.calls_for("shops", "select") == []


def test_all_sellers_counts_shops_past_1000(admin_db):
    admin_db.responses[("shops", "select")] = [{"id": f"s{i}", "owner_id": OWNER} for i in range(2500)]
    pages = [[SimpleNamespace(id=OWNER, email="o@test.local", email_confirmed_at="x", last_sign_in_at=None,
                              created_at=NOW_ISO)], []]

    def list_users(page=1, per_page=200):
        return pages[min(page - 1, 1)]

    admin_db.auth = SimpleNamespace(admin=SimpleNamespace(list_users=list_users))

    r = _get("/admin/sellers")

    assert r.status_code == 200, r.text
    (row,) = r.json()
    assert row["id"] == OWNER and row["shops"] == 2500
    assert admin_db.calls_for("shops", "select")[0].orders[-1] == ("id", False)


def test_shop_detail_returns_all_products(admin_db):
    admin_db.responses[("shops", "select")] = [{"id": SHOP_A, "name": "A", "facebook_page_token": "secret"}]
    admin_db.responses[("products", "select")] = [{"id": f"p{i}", "shop_id": SHOP_A} for i in range(2500)]

    r = _get(f"/admin/shops/{SHOP_A}")

    assert r.status_code == 200
    body = r.json()
    assert len(body["products"]) == 2500
    assert "facebook_page_token" not in body["shop"]
    pages = admin_db.calls_for("products", "select")
    assert pages[0].orders == [("name", False), ("id", False)]
    assert ("eq", "shop_id", SHOP_A) in pages[0].filters


def test_upgrade_requests_load_only_requesting_shops(admin_db):
    admin_db.responses[("upgrade_requests", "select")] = [
        {"id": "r1", "shop_id": SHOP_B, "requested_tier": "standard", "status": "pending"},
        {"id": "r2", "shop_id": SHOP_A, "requested_tier": "basic", "status": "pending"},
        {"id": "r3", "shop_id": SHOP_A, "requested_tier": "basic", "status": "pending"},
    ]
    admin_db.responses[("shops", "select")] = [
        {"id": SHOP_A, "name": "A", "subscription_tier": "free", "owner_id": OWNER},
        {"id": SHOP_B, "name": "B", "subscription_tier": "basic", "owner_id": OWNER},
    ]

    r = _get("/admin/upgrade-requests")

    assert r.status_code == 200, r.text
    assert [(x["shop_name"], x["current_tier"]) for x in r.json()] == [("B", "basic"), ("A", "free"), ("A", "free")]
    (shop_q,) = admin_db.calls_for("shops", "select")
    assert shop_q.filters == [("in", "id", sorted([SHOP_A, SHOP_B]))]


def test_upgrade_requests_empty_does_not_query_shops(admin_db):
    admin_db.responses[("upgrade_requests", "select")] = []

    r = _get("/admin/upgrade-requests")

    assert r.status_code == 200 and r.json() == []
    assert admin_db.calls_for("shops", "select") == []
