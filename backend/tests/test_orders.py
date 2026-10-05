"""F-03B: abuse limits on the public POST /orders endpoint."""
import app.api.orders as orders

SHOP_ID = "22222222-2222-2222-2222-222222222222"
PRODUCT_ID = "33333333-3333-3333-3333-333333333333"
VALID_PHONE = "+995 555 12-34-56"


def _setup(db, recent_orders=0):
    db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    db.responses[("products", "select")] = [
        {"id": PRODUCT_ID, "name": "Test Product", "price": 5, "quantity": 100}
    ]
    db.counts[("orders", "select")] = recent_orders
    db.responses[("orders", "insert")] = [{"id": "44444444-4444-4444-4444-444444444444"}]


def _order(quantities, phone=VALID_PHONE):
    body = {
        "shop_id": SHOP_ID,
        "customer_name": "Buyer",
        "customer_address": "Tbilisi",
        "items": [{"product_id": PRODUCT_ID, "name": "x", "quantity": q} for q in quantities],
    }
    if phone is not None:
        body["customer_phone"] = phone
    return body


def _assert_nothing_written(db):
    assert db.rpc_calls == []
    assert db.calls_for("orders", "insert") == []
    assert db.calls_for("products", "update") == []


def test_o1_single_item_over_limit_rejected(client, service_db):
    _setup(service_db)
    res = client.post("/orders", json=_order([orders.MAX_ITEM_QTY + 1]))
    assert res.status_code == 400
    assert "მაქსიმუმ 10 ცალი" in res.json()["detail"]
    assert "Test Product" in res.json()["detail"]
    _assert_nothing_written(service_db)


def test_o2_duplicate_lines_summed_per_product(client, service_db):
    _setup(service_db)
    res = client.post("/orders", json=_order([6, 6]))
    assert res.status_code == 400
    assert "მაქსიმუმ 10 ცალი" in res.json()["detail"]
    _assert_nothing_written(service_db)


def test_o3_missing_or_invalid_phone_rejected(client, service_db):
    _setup(service_db)
    for phone in (None, "abc"):
        res = client.post("/orders", json=_order([1], phone=phone))
        assert res.status_code == 400, phone
        assert res.json()["detail"] == "მიუთითეთ სწორი ტელეფონის ნომერი"
    _assert_nothing_written(service_db)


def test_o4_shop_hourly_cap(client, service_db):
    _setup(service_db, recent_orders=orders.SHOP_ORDERS_PER_HOUR)
    res = client.post("/orders", json=_order([1]))
    assert res.status_code == 429
    assert "ძალიან ბევრი შეკვეთა" in res.json()["detail"]
    _assert_nothing_written(service_db)
    count_query = service_db.calls_for("orders", "select")[0]
    assert ("eq", "shop_id", SHOP_ID) in count_query.filters
    assert any(f[0] == "gte" and f[1] == "created_at" for f in count_query.filters)


def test_o5_valid_order_at_limit_accepted(client, service_db):
    _setup(service_db, recent_orders=orders.SHOP_ORDERS_PER_HOUR - 1)
    res = client.post("/orders", json=_order([orders.MAX_ITEM_QTY]))
    assert res.status_code == 201, res.text
    assert len(service_db.rpc_calls) == 1
    assert service_db.rpc_calls[0].fn == "decrement_stock"
    assert len(service_db.calls_for("orders", "insert")) == 1
