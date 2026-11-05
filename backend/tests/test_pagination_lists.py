"""Stage 22 (S22-2, A-041): გამყიდველის / საჯარო / ბოტის სიები `fetch_all`-ით — 1000-მწკრივიანი
ჭერის მიღმაც სრულად (ბოტი, პროდუქტები, import, შეკვეთები, საჯარო მენიუ, ექსპორტი).

FakeSupabase-ი `range`-ის გარეშე select-ზე 1000-ზე მეტს არ აბრუნებს (S22-1) — ამიტომ 2 500 მწკრივი
ძველ კოდზე 1 000-ად იჭრება და ტესტი ვარდება."""
import json
import logging
import uuid

import pytest

import app.api.orders as orders_api
import app.api.products as products_api
import app.api.shops as shops_api
import app.api.webhook as webhook

SHOP_ID = str(uuid.uuid4())
N = 2500
DETAIL_EXPORT = "მონაცემი ექსპორტისთვის ძალიან დიდია — მიმართეთ მხარდაჭერას."
DETAIL_IMPORT = "კატალოგი ძალიან დიდია იმპორტისთვის — მიმართეთ მხარდაჭერას."


def _product(i, **extra):
    row = {
        "id": str(uuid.UUID(int=i + 1)), "shop_id": SHOP_ID, "name": f"Product {i}", "description": None,
        "sku": f"SKU-{i}", "price": 1.5, "quantity": 3, "image_url": None, "is_active": True,
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
    }
    row.update(extra)
    return row


def _order(i):
    return {
        "id": str(uuid.UUID(int=i + 1)), "shop_id": SHOP_ID, "customer_name": "Name", "customer_phone": None,
        "customer_address": None, "note": None, "items": [], "total": 1.0, "status": "new",
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
    }


def _ranges(calls):
    return [c.range_ for c in calls]


# ── list_products ──

def test_list_products_returns_more_than_1000(client, user_db):
    user_db.responses[("products", "select")] = [_product(i) for i in range(N)]
    r = client.get("/products")
    assert r.status_code == 200
    assert len(r.json()) == N
    calls = user_db.calls_for("products", "select")
    assert _ranges(calls) == [(0, 999), (1000, 1999), (2000, 2999)]
    assert calls[0].orders == [("created_at", False), ("id", False)]


def test_list_products_shop_filter_kept_on_every_page(client, user_db):
    user_db.responses[("products", "select")] = [_product(i) for i in range(N)]
    r = client.get("/products", params={"shop_id": SHOP_ID})
    assert r.status_code == 200 and len(r.json()) == N
    for c in user_db.calls_for("products", "select"):
        assert ("eq", "shop_id", SHOP_ID) in c.filters


# ── list_orders ──

def test_list_orders_returns_more_than_1000(client, user_db):
    user_db.responses[("orders", "select")] = [_order(i) for i in range(N)]
    r = client.get("/orders", params={"status": "new", "shop_id": SHOP_ID})
    assert r.status_code == 200
    assert len(r.json()) == N
    calls = user_db.calls_for("orders", "select")
    assert len(calls) == 3
    for c in calls:
        assert c.orders == [("created_at", True), ("id", True)]
        assert ("eq", "status", "new") in c.filters and ("eq", "shop_id", SHOP_ID) in c.filters


# ── public_menu ──

def test_public_menu_returns_all_active_products(client, service_db):
    service_db.responses[("shops", "select")] = [{"id": SHOP_ID, "name": "Shop", "currency": "GEL"}]
    service_db.responses[("products", "select")] = [
        {"id": f"p{i}", "name": f"P{i}", "price": 1, "quantity": 2, "description": None} for i in range(N)
    ]
    r = client.get("/public-menu", params={"shop_id": SHOP_ID})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"shop", "products"}
    assert len(body["products"]) == N
    for c in service_db.calls_for("products", "select"):
        assert ("eq", "shop_id", SHOP_ID) in c.filters and ("eq", "is_active", True) in c.filters
        assert c.orders == [("name", False), ("id", False)]


# ── ბოტის პროდუქტები ──

def _patch_columns(monkeypatch, db, fail_with_description=False):
    """products select-ის სვეტები ჩაიწერება; `image_description`-იანი ვარიანტი (0028-მდე) ვარდება."""
    query_cls = type(db.table("x"))
    real_select, real_execute = query_cls.select, query_cls.execute
    seen = []

    def select(self, *columns, **kwargs):
        self.columns = columns
        return real_select(self, *columns, **kwargs)

    def execute(self):
        if self.table == "products" and self.op == "select":
            seen.append(self.columns)
            if fail_with_description and "image_description" in ",".join(self.columns):
                raise RuntimeError("column products.image_description does not exist")
        return real_execute(self)

    monkeypatch.setattr(query_cls, "select", select)
    monkeypatch.setattr(query_cls, "execute", execute)
    return seen


def test_bot_products_loaded_past_1000(service_db):
    service_db.responses[("products", "select")] = [{"id": f"p{i}", "name": f"P{i}"} for i in range(N)]
    out = webhook._load_bot_products(service_db, SHOP_ID)
    assert len(out) == N
    calls = service_db.calls_for("products", "select")
    assert _ranges(calls) == [(0, 999), (1000, 1999), (2000, 2999)]
    for c in calls:
        assert ("eq", "shop_id", SHOP_ID) in c.filters and ("eq", "is_active", True) in c.filters
        assert c.orders == [("id", False)]


def test_bot_products_fallback_without_image_description_is_paged_too(monkeypatch, service_db):
    seen = _patch_columns(monkeypatch, service_db, fail_with_description=True)
    service_db.responses[("products", "select")] = [{"id": f"p{i}", "name": f"P{i}"} for i in range(N)]
    out = webhook._load_bot_products(service_db, SHOP_ID)
    assert len(out) == N
    # პირველი ვარიანტი პირველ გვერდზე ვარდება (1 query), მეორე — 3 გვერდი
    assert len(seen) == 4
    assert "image_description" in ",".join(seen[0])
    assert all("image_description" not in ",".join(c) for c in seen[1:])


def test_bot_products_cap_truncates_with_warning(monkeypatch, service_db, caplog):
    monkeypatch.setattr(webhook, "_BOT_PRODUCTS_MAX", 5)
    service_db.responses[("products", "select")] = [{"id": f"p{i}", "name": f"SecretName{i}"} for i in range(6)]
    with caplog.at_level(logging.WARNING, logger="app"):
        out = webhook._load_bot_products(service_db, SHOP_ID)
    assert len(out) == 5
    assert "bot products" in caplog.text and "truncated" in caplog.text
    assert "SecretName" not in caplog.text


# ── ექსპორტი ──

def _export_db(user_db, n_products, n_orders):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "name": "Shop", "facebook_page_token": "secret"}]
    user_db.responses[("products", "select")] = [_product(i) for i in range(n_products)]
    user_db.responses[("orders", "select")] = [_order(i) for i in range(n_orders)]


def test_export_contains_all_rows(client, user_db):
    _export_db(user_db, N, N)
    r = client.get(f"/shops/{SHOP_ID}/export")
    assert r.status_code == 200
    body = json.loads(r.content)
    assert set(body) == {"exported_at", "shop", "products", "orders"}
    assert len(body["products"]) == N and len(body["orders"]) == N
    assert "facebook_page_token" not in body["shop"]
    for c in user_db.calls_for("products", "select"):
        assert c.orders == [("name", False), ("id", False)]
    for c in user_db.calls_for("orders", "select"):
        assert c.orders == [("created_at", True), ("id", True)]


@pytest.mark.parametrize("n_products,n_orders", [(11, 3), (3, 11)])
def test_export_too_large_returns_413(monkeypatch, client, user_db, n_products, n_orders):
    monkeypatch.setattr(shops_api, "_EXPORT_MAX", 10)
    _export_db(user_db, n_products, n_orders)
    r = client.get(f"/shops/{SHOP_ID}/export")
    assert r.status_code == 413
    assert r.json() == {"detail": DETAIL_EXPORT}


def test_export_exactly_at_cap_is_complete(monkeypatch, client, user_db):
    monkeypatch.setattr(shops_api, "_EXPORT_MAX", 10)
    _export_db(user_db, 10, 10)
    r = client.get(f"/shops/{SHOP_ID}/export")
    assert r.status_code == 200
    body = json.loads(r.content)
    assert len(body["products"]) == 10 and len(body["orders"]) == 10


# ── import ──

@pytest.fixture
def import_env(monkeypatch, user_db):
    monkeypatch.setattr(products_api, "bulk_import_allowed", lambda tier: True)
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "business"}]
    return user_db


def _upload(client, csv_text):
    return client.post(
        "/products/import",
        data={"shop_id": SHOP_ID},
        files={"file": ("p.csv", csv_text.encode(), "text/csv")},
    )


def test_import_matches_existing_product_beyond_1000(client, import_env):
    import_env.responses[("products", "select")] = [
        {"id": f"id-{i}", "sku": f"SKU-{i}", "name": f"Item {i}"} for i in range(1500)
    ]
    r = _upload(client, "name,sku,price\nRenamed,SKU-1400,5\n")
    assert r.status_code == 200
    assert r.json()["updated"] == 1 and r.json()["imported"] == 0
    updates = import_env.calls_for("products", "update")
    assert len(updates) == 1 and ("eq", "id", "id-1400") in updates[0].filters
    assert import_env.calls_for("products", "insert") == []


def test_import_existing_read_is_paged_with_unique_order(client, import_env):
    import_env.responses[("products", "select")] = [
        {"id": f"id-{i}", "sku": f"SKU-{i}", "name": f"Item {i}"} for i in range(1500)
    ]
    _upload(client, "name,sku,price\nRenamed,SKU-1400,5\n")
    paged = [c for c in import_env.calls_for("products", "select") if c.range_ is not None]
    assert _ranges(paged) == [(0, 999), (1000, 1999)]
    assert all(c.orders == [("id", False)] and ("eq", "shop_id", SHOP_ID) in c.filters for c in paged)


def test_import_existing_over_cap_returns_413_and_writes_nothing(monkeypatch, client, import_env):
    monkeypatch.setattr(products_api, "_IMPORT_EXISTING_MAX", 10)
    import_env.responses[("products", "select")] = [
        {"id": f"id-{i}", "sku": f"SKU-{i}", "name": f"Item {i}"} for i in range(11)
    ]
    r = _upload(client, "name,sku,price\nRenamed,SKU-1,5\nNew,SKU-NEW,1\n")
    assert r.status_code == 413
    assert r.json() == {"detail": DETAIL_IMPORT}
    assert import_env.calls_for("products", "update") == []
    assert import_env.calls_for("products", "insert") == []


# ── ჭერის გადაჭარბება: ჭრა + WARNING (200), ლოგში მონაცემი არ არის ──

def test_list_truncation_logs_warning(monkeypatch, client, user_db, caplog):
    monkeypatch.setattr(products_api, "_LIST_MAX", 5)
    user_db.responses[("products", "select")] = [_product(i, name=f"SecretName{i}") for i in range(6)]
    with caplog.at_level(logging.WARNING, logger="app"):
        r = client.get("/products")
    assert r.status_code == 200
    assert len(r.json()) == 5
    assert "list_products" in caplog.text and "truncated" in caplog.text
    assert "SecretName" not in caplog.text


def test_list_orders_truncation_keeps_newest_and_logs_warning(monkeypatch, client, user_db, caplog):
    monkeypatch.setattr(orders_api, "_LIST_MAX", 5)
    user_db.responses[("orders", "select")] = [_order(i) for i in range(6)]
    with caplog.at_level(logging.WARNING, logger="app"):
        r = client.get("/orders")
    assert r.status_code == 200 and len(r.json()) == 5
    assert "truncated" in caplog.text


def test_public_menu_truncation_logs_warning(monkeypatch, client, service_db, caplog):
    monkeypatch.setattr(orders_api, "_MENU_MAX", 5)
    service_db.responses[("shops", "select")] = [{"id": SHOP_ID, "name": "Shop", "currency": "GEL"}]
    service_db.responses[("products", "select")] = [
        {"id": f"p{i}", "name": f"SecretName{i}", "price": 1, "quantity": 2, "description": None}
        for i in range(6)
    ]
    with caplog.at_level(logging.WARNING, logger="app"):
        r = client.get("/public-menu", params={"shop_id": SHOP_ID})
    assert r.status_code == 200 and len(r.json()["products"]) == 5
    assert "truncated" in caplog.text and "SecretName" not in caplog.text


# ── ყველა გვერდიანი query unique სვეტით მთავრდება ──

def test_every_paged_query_ends_with_id_order(monkeypatch, client, user_db, service_db):
    monkeypatch.setattr(products_api, "bulk_import_allowed", lambda tier: True)
    user_db.responses[("shops", "select")] = [
        {"id": SHOP_ID, "name": "Shop", "subscription_tier": "business", "currency": "GEL"}
    ]
    user_db.responses[("products", "select")] = [_product(i) for i in range(30)]
    user_db.responses[("orders", "select")] = [_order(i) for i in range(30)]
    service_db.responses[("shops", "select")] = [{"id": SHOP_ID, "name": "Shop", "currency": "GEL"}]
    service_db.responses[("products", "select")] = [
        {"id": f"p{i}", "name": f"P{i}", "price": 1, "quantity": 1, "description": None} for i in range(30)
    ]
    assert client.get("/products").status_code == 200
    assert client.get("/orders").status_code == 200
    assert client.get(f"/shops/{SHOP_ID}/export").status_code == 200
    assert _upload(client, "name,sku,price\nX,SKU-1,5\n").status_code == 200
    assert client.get("/public-menu", params={"shop_id": SHOP_ID}).status_code == 200
    webhook._load_bot_products(service_db, SHOP_ID)

    paged = [
        c for db in (user_db, service_db) for c in db.calls
        if c.op == "select" and c.range_ is not None
    ]
    assert len(paged) >= 7  # products, orders, export x2, import existing, public menu, bot
    for c in paged:
        assert c.orders and c.orders[-1][0] == "id", (c.table, c.orders)
