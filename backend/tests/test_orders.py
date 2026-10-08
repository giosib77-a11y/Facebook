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
        "form_ms": 5000,
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
    from datetime import datetime, timedelta, timezone

    def _created_since_age(q):
        """Age of the query's `created_at >= …` bound, or None if it has none."""
        for op, col, val in q.filters:
            if op == "gte" and col == "created_at":
                return datetime.now(timezone.utc) - datetime.fromisoformat(val)
        return None

    # Pick the hourly-cap query by its own window (~1h), not by list position.
    hourly = [
        q for q in service_db.calls_for("orders", "select")
        if (age := _created_since_age(q)) is not None
        and timedelta(minutes=55) <= age <= timedelta(minutes=65)
    ]
    assert len(hourly) == 1
    count_query = hourly[0]
    assert ("eq", "shop_id", SHOP_ID) in count_query.filters
    assert not any(f[1] == "status" for f in count_query.filters)


def test_o5_valid_order_at_limit_accepted(client, service_db):
    _setup(service_db, recent_orders=orders.SHOP_ORDERS_PER_HOUR - 1)
    res = client.post("/orders", json=_order([orders.MAX_ITEM_QTY]))
    assert res.status_code == 201, res.text
    assert service_db.rpc_calls == []  # B-1: creating an order never touches stock
    assert service_db.calls_for("products", "update") == []
    assert len(service_db.calls_for("orders", "insert")) == 1


def test_o6_order_creation_leaves_stock_unchanged(client, service_db):
    _setup(service_db)
    res = client.post("/orders", json=_order([3]))
    assert res.status_code == 201, res.text
    assert service_db.rpc_calls == []
    assert service_db.calls_for("products", "update") == []
    assert service_db.calls_for("orders", "insert")[0].payload["status"] == "new"


def test_o7_order_over_available_stock_rejected_without_write(client, service_db):
    _setup(service_db)
    service_db.responses[("products", "select")] = [
        {"id": PRODUCT_ID, "name": "Test Product", "price": 5, "quantity": 2}
    ]
    res = client.post("/orders", json=_order([3]))
    assert res.status_code == 400, res.text
    assert "მარაგში მხოლოდ 2 ცალია" in res.json()["detail"]
    _assert_nothing_written(service_db)


def test_o8_insert_failure_returns_400_and_no_stock_calls(client, service_db):
    _setup(service_db)
    service_db.responses[("orders", "insert")] = []
    res = client.post("/orders", json=_order([1]))
    assert res.status_code == 400, res.text
    assert service_db.rpc_calls == []


def test_o9_daily_ip_limit_returns_429(client, service_db):
    from app.core import ratelimit

    _setup(service_db)
    # per-minute bucket (10) would trip first, so pre-fill the daily bucket directly
    now = ratelimit.time.monotonic()
    hits = [now] * orders.PUBLIC_ORDERS_PER_IP_PER_DAY
    ratelimit._HITS["create_order_day"]["testclient"].extend(hits)
    res = client.post("/orders", json=_order([1]))
    assert res.status_code == 429, res.text
    assert "Retry-After" in res.headers
    _assert_nothing_written(service_db)


def test_o10_below_daily_limit_accepted(client, service_db):
    from app.core import ratelimit

    _setup(service_db)
    now = ratelimit.time.monotonic()
    hits = [now] * (orders.PUBLIC_ORDERS_PER_IP_PER_DAY - 1)
    ratelimit._HITS["create_order_day"]["testclient"].extend(hits)
    res = client.post("/orders", json=_order([1]))
    assert res.status_code == 201, res.text


def test_o11_daily_bucket_survives_short_window_sweep():
    from app.core import ratelimit

    now = ratelimit.time.monotonic()
    ratelimit._HITS["create_order_day"]["1.2.3.4"].append(now - 3600)
    ratelimit._last_sweep[0] = now - 1000  # force a sweep
    ratelimit._sweep(now)
    assert len(ratelimit._HITS["create_order_day"]["1.2.3.4"]) == 1


# ---------- B-1/F-06: stock is taken atomically on entering processing/done ----------
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


def _take_params():
    return {"p_shop_id": SHOP_ID, "p_items": [{"product_id": PRODUCT_ID, "quantity": 2}]}


def test_s1_new_to_processing_decrements_atomically(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "new", "processing")
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "processing"})
    assert res.status_code == 200, res.text
    dec = _rpcs(service_db, "decrement_stock")
    assert len(dec) == 1
    assert dec[0].params == _take_params()
    assert len(user_db.calls_for("orders", "update")) == 1
    assert _rpcs(service_db, "apply_stock_delta") == []


def test_s2_processing_with_insufficient_stock_is_409(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "new", "processing")
    service_db.rpc_errors["decrement_stock"] = APIError(
        {"message": "INSUFFICIENT_STOCK|Test Product|1", "code": "P0001"}
    )
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "processing"})
    assert res.status_code == 409, res.text
    assert res.json()["detail"] == (
        "შეკვეთის დადასტურება შეუძლებელია — მარაგი არასაკმარისია: Test Product"
    )
    assert user_db.calls_for("orders", "update") == []
    assert _rpcs(service_db, "apply_stock_delta") == []


def test_s3_status_conflict_returns_taken_stock(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "new", "processing", update_matches=False)
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "processing"})
    assert res.status_code == 409, res.text
    assert "სტატუსი ამასობაში შეიცვალა" in res.json()["detail"]
    assert len(_rpcs(service_db, "decrement_stock")) == 1
    comp = _rpcs(service_db, "apply_stock_delta")
    assert len(comp) == 1
    assert comp[0].params == {**_take_params(), "p_sign": 1}


def test_s4_cancel_from_new_does_not_touch_stock(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "new", "cancelled")
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "cancelled"})
    assert res.status_code == 200, res.text
    assert service_db.rpc_calls == []


def test_s5_cancel_from_processing_returns_stock(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "processing", "cancelled")
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "cancelled"})
    assert res.status_code == 200, res.text
    assert _rpcs(service_db, "decrement_stock") == []
    delta = _rpcs(service_db, "apply_stock_delta")
    assert len(delta) == 1
    assert delta[0].params == {**_take_params(), "p_sign": 1}


def test_s6_cancel_from_done_returns_stock(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "done", "cancelled")
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "cancelled"})
    assert res.status_code == 200, res.text
    assert len(_rpcs(service_db, "apply_stock_delta")) == 1


def test_s7_processing_to_done_leaves_stock_alone(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "processing", "done")
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "done"})
    assert res.status_code == 200, res.text
    assert service_db.rpc_calls == []


def test_s8_reopen_cancelled_to_new_takes_no_stock(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "cancelled", "new")
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "new"})
    assert res.status_code == 200, res.text
    assert service_db.rpc_calls == []


def test_s9_reopen_cancelled_to_processing_takes_stock(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "cancelled", "processing")
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "processing"})
    assert res.status_code == 200, res.text
    assert len(_rpcs(service_db, "decrement_stock")) == 1


def test_s10_processing_back_to_new_returns_stock(client, user_db, service_db):
    _setup_status_change(user_db, service_db, "processing", "new")
    res = client.patch(f"/orders/{ORDER_ID}", json={"status": "new"})
    assert res.status_code == 200, res.text
    assert len(_rpcs(service_db, "apply_stock_delta")) == 1


# ---------- F-07: only terminal orders can be deleted (stock stays reserved) ----------
ACTIVE_DELETE_MSG = (
    "აქტიური შეკვეთის წაშლა შეუძლებელია — ჯერ გააუქმეთ შეკვეთა (თუ ის „მუშავდება“ იყო, მარაგი დაბრუნდება)."
)


def _setup_delete(user_db, status):
    """`status=None` → order doesn't exist. The fake ignores filters, so the DELETE
    result is set to what Postgres would return for `status IN (done, cancelled)`."""
    if status is None:
        return
    user_db.responses[("orders", "select")] = [{"id": ORDER_ID}]
    if status in ("done", "cancelled"):
        user_db.responses[("orders", "delete")] = [_order_row(status)]


def _assert_delete_filtered(user_db):
    dq = user_db.calls_for("orders", "delete")
    assert len(dq) == 1
    assert ("eq", "id", ORDER_ID) in dq[0].filters
    assert ("in", "status", ["done", "cancelled"]) in dq[0].filters


def test_d1_delete_new_order_rejected(client, user_db, service_db):
    _setup_delete(user_db, "new")
    res = client.delete(f"/orders/{ORDER_ID}")
    assert res.status_code == 409, res.text
    assert res.json()["detail"] == ACTIVE_DELETE_MSG
    _assert_delete_filtered(user_db)
    assert service_db.rpc_calls == []
    assert user_db.rpc_calls == []


def test_d2_delete_processing_order_rejected(client, user_db, service_db):
    _setup_delete(user_db, "processing")
    res = client.delete(f"/orders/{ORDER_ID}")
    assert res.status_code == 409, res.text
    assert res.json()["detail"] == ACTIVE_DELETE_MSG
    _assert_delete_filtered(user_db)
    assert service_db.rpc_calls == []


def test_d3_delete_cancelled_order_ok(client, user_db, service_db):
    _setup_delete(user_db, "cancelled")
    res = client.delete(f"/orders/{ORDER_ID}")
    assert res.status_code == 204, res.text
    assert res.content == b""
    _assert_delete_filtered(user_db)
    assert service_db.rpc_calls == []


def test_d4_delete_done_order_ok(client, user_db, service_db):
    _setup_delete(user_db, "done")
    res = client.delete(f"/orders/{ORDER_ID}")
    assert res.status_code == 204, res.text
    assert res.content == b""
    _assert_delete_filtered(user_db)
    assert service_db.rpc_calls == []


def test_d5_delete_missing_order_404(client, user_db, service_db):
    _setup_delete(user_db, None)
    res = client.delete(f"/orders/{ORDER_ID}")
    assert res.status_code == 404, res.text
    assert res.json()["detail"] == "შეკვეთა ვერ მოიძებნა ან არ არის თქვენი"
    assert service_db.rpc_calls == []


def test_o_b4_product_query_filters_active_only(client, service_db):
    _setup(service_db)
    res = client.post("/orders", json=_order([1]))
    assert res.status_code == 201, res.text
    q = service_db.calls_for("products", "select")[0]
    assert ("eq", "is_active", True) in q.filters
    assert ("eq", "shop_id", SHOP_ID) in q.filters


def test_o_b4_inactive_product_rejected_without_write(client, service_db):
    _setup(service_db)
    # the is_active=true filter makes the DB return no row for an inactive product
    service_db.responses[("products", "select")] = []
    res = client.post("/orders", json=_order([1]))
    assert res.status_code == 400
    assert "ვერ მოიძებნა" in res.json()["detail"]
    _assert_nothing_written(service_db)
