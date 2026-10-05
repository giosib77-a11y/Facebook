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


# ---------- F-06: re-opening a cancelled order takes stock atomically ----------
from postgrest.exceptions import APIError  # noqa: E402

ORDER_ID = "55555555-5555-5555-5555-555555555555"
ORDER_ITEMS = [{"product_id": PRODUCT_ID, "name": "Test Product", "price": 5, "quantity": 2}]


def _order_row(status):
    return {
        "id": ORDER_ID,
        "shop_id": SHOP_ID,
        "customer_name": "Buyer",
        "items": ORDER_ITEMS,
        "total": 10,
        "status": status,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }


def _setup_status_change(user_db, service_db, old_status, new_status, update_matches=True):
    user_db.responses[("orders", "select")] = [
        {"status": old_status, "items": ORDER_ITEMS, "shop_id": SHOP_ID}
    ]
    if update_matches:
        user_db.responses[("orders", "update")] = [_order_row(new_status)]
    service_db.responses[("products", "select")] = [{"id": PRODUCT_ID}]


def _rpcs(db, fn):
    return [c for c in db.rpc_calls if c.fn == fn]


def test_s1_reopen_with_enough_stock_decrements_atomically(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "cancelled", "new")
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "new"})
    assert res.status_code == 200, res.text
    dec = _rpcs(service_db, "decrement_stock")
    assert len(dec) == 1
    assert dec[0].params == {
        "p_shop_id": SHOP_ID,
        "p_items": [{"product_id": PRODUCT_ID, "quantity": 2}],
    }
    assert len(user_db.calls_for("orders", "update")) == 1
    assert _rpcs(service_db, "apply_stock_delta") == []


def test_s2_reopen_with_insufficient_stock_rejected(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "cancelled", "new")
    service_db.rpc_errors["decrement_stock"] = APIError(
        {"message": "INSUFFICIENT_STOCK|Test Product|1", "code": "P0001"}
    )
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "new"})
    assert res.status_code == 409, res.text
    assert res.json()["detail"] == (
        "შეკვეთის აღდგენა შეუძლებელია — მარაგი არასაკმარისია: Test Product"
    )
    assert user_db.calls_for("orders", "update") == []
    assert _rpcs(service_db, "apply_stock_delta") == []


def test_s3_reopen_status_conflict_returns_taken_stock(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "cancelled", "new", update_matches=False)
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "new"})
    assert res.status_code == 409, res.text
    assert "სტატუსი ამასობაში შეიცვალა" in res.json()["detail"]
    assert len(_rpcs(service_db, "decrement_stock")) == 1
    comp = _rpcs(service_db, "apply_stock_delta")
    assert len(comp) == 1
    assert comp[0].params == {
        "p_shop_id": SHOP_ID,
        "p_items": [{"product_id": PRODUCT_ID, "quantity": 2}],
        "p_sign": 1,
    }


def test_s4_cancel_still_returns_stock(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "new", "cancelled")
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "cancelled"})
    assert res.status_code == 200, res.text
    assert _rpcs(service_db, "decrement_stock") == []
    delta = _rpcs(service_db, "apply_stock_delta")
    assert len(delta) == 1
    assert delta[0].params["p_sign"] == 1
