"""A-038 (N-07): POST /orders schedules the new-order email (BackgroundTask) - only for a really new order.

Offline: FakeSupabase from conftest; `app.api.orders.notify` is replaced, so nothing is ever sent.
"""
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

SHOP_ID = "22222222-2222-2222-2222-222222222222"
PRODUCT_ID = "33333333-3333-3333-3333-333333333333"
ORDER_ID = "44444444-4444-4444-4444-444444444444"
KEY = "55555555-5555-4555-8555-555555555555"


@pytest.fixture
def notified(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.api.orders.notify",
        SimpleNamespace(notify_new_order=lambda *a, **kw: calls.append((a, kw))),
    )
    return calls


def _setup(db):
    db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    db.responses[("products", "select")] = [
        {"id": PRODUCT_ID, "name": "Test Product", "price": 5, "quantity": 100}
    ]
    db.counts[("orders", "select")] = 0
    db.responses[("orders", "insert")] = [{"id": ORDER_ID}]


def _order(key=None, **over):
    body = {
        "shop_id": SHOP_ID,
        "customer_name": "Buyer",
        "customer_phone": "+995 555 12-34-56",
        "items": [{"product_id": PRODUCT_ID, "name": "x", "quantity": 2}],
        "form_ms": 5000,
    }
    if key is not None:
        body["idempotency_key"] = key
    body.update(over)
    return body


def test_valid_order_schedules_notification_once(client, service_db, notified):
    _setup(service_db)
    r = client.post("/orders", json=_order())
    assert r.status_code == 201
    assert r.json() == {"ok": True, "order_id": ORDER_ID, "total": 10.0}  # response unchanged
    assert notified == [((SHOP_ID, ORDER_ID, 10.0), {})]


def test_valid_order_with_idempotency_key_notifies_once(client, service_db, notified):
    _setup(service_db)
    r = client.post("/orders", json=_order(key=KEY))
    assert r.status_code == 201
    assert notified == [((SHOP_ID, ORDER_ID, 10.0), {})]


def test_idempotent_replay_does_not_notify(client, service_db, notified):
    _setup(service_db)
    service_db.responses[("orders", "select")] = [{"id": ORDER_ID, "total": 10.0}]  # key already stored
    r = client.post("/orders", json=_order(key=KEY))
    assert r.status_code == 201
    assert r.json() == {"ok": True, "order_id": ORDER_ID, "total": 10.0}
    assert service_db.calls_for("orders", "insert") == []
    assert notified == []


def test_unique_violation_path_does_not_notify(client, service_db, notified):
    _setup(service_db)
    service_db.errors[("orders", "insert")] = APIError(
        {"code": "23505", "message": "duplicate key value violates unique constraint"}
    )

    class _Responses(dict):
        def get(self, k, default=None):
            if k == ("orders", "select") and service_db.calls_for("orders", "insert"):
                return [{"id": ORDER_ID, "total": 10.0}]
            return super().get(k, default)

    service_db.responses = _Responses(service_db.responses)
    r = client.post("/orders", json=_order(key=KEY))
    assert r.status_code == 201
    assert r.json()["order_id"] == ORDER_ID
    assert notified == []


def test_insert_failure_does_not_notify(client, service_db, notified):
    _setup(service_db)
    service_db.errors[("orders", "insert")] = RuntimeError("db down")
    r = client.post("/orders", json=_order())
    assert r.status_code == 400
    assert notified == []


def test_insert_without_returned_row_does_not_notify(client, service_db, notified):
    _setup(service_db)
    service_db.responses[("orders", "insert")] = []
    r = client.post("/orders", json=_order())
    assert r.status_code == 400
    assert notified == []


@pytest.mark.parametrize(
    "over",
    [
        {"form_ms": 100},  # too fast (bot)
        {"website": "http://spam.test"},  # honeypot
        {"customer_phone": "abc"},  # invalid phone
    ],
)
def test_rejected_order_400_does_not_notify(client, service_db, notified, over):
    _setup(service_db)
    r = client.post("/orders", json=_order(**over))
    assert r.status_code == 400
    assert service_db.calls_for("orders", "insert") == []
    assert notified == []


def test_open_orders_per_phone_429_does_not_notify(client, service_db, notified):
    _setup(service_db)
    service_db.responses[("orders", "select")] = [{"customer_phone": "+995 555 12-34-56"}] * 3
    r = client.post("/orders", json=_order())
    assert r.status_code == 429
    assert notified == []


def test_shop_hourly_limit_429_does_not_notify(client, service_db, notified):
    _setup(service_db)
    service_db.counts[("orders", "select")] = 30
    r = client.post("/orders", json=_order())
    assert r.status_code == 429
    assert notified == []


def test_unknown_shop_404_does_not_notify(client, service_db, notified):
    _setup(service_db)
    service_db.responses[("shops", "select")] = []
    r = client.post("/orders", json=_order())
    assert r.status_code == 404
    assert notified == []
