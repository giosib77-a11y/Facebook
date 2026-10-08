"""FA-04: honeypot, minimum fill time and per-phone open-order cap on POST /orders."""
import pytest

from app.core import ratelimit
from tests.test_orders import SHOP_ID, VALID_PHONE, _assert_nothing_written, _order, _setup

PHONE_CAP_MSG = (
    "ამ ნომრიდან უკვე გაქვთ 3 დაუდასტურებელი შეკვეთა. "
    "დაელოდეთ მაღაზიის პასუხს ან მიწერეთ Messenger-ში."
)


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    ratelimit._HITS.clear()
    yield
    ratelimit._HITS.clear()


def _open_orders(db, phones):
    db.responses[("orders", "select")] = [{"customer_phone": p} for p in phones]


def test_a1_honeypot_filled_rejected(client, service_db):
    _setup(service_db)
    res = client.post("/orders", json={**_order([1]), "website": "http://spam.example"})
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == "შეკვეთის შექმნა ვერ მოხერხდა"
    _assert_nothing_written(service_db)


def test_a2_form_filled_too_fast_rejected(client, service_db):
    _setup(service_db)
    res = client.post("/orders", json={**_order([1]), "form_ms": 1000})
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == "გთხოვთ, შეავსეთ ფორმა და სცადეთ თავიდან."
    _assert_nothing_written(service_db)


def test_a3_form_ms_missing_is_422(client, service_db):
    _setup(service_db)
    body = _order([1])
    del body["form_ms"]
    res = client.post("/orders", json=body)
    assert res.status_code == 422, res.text
    _assert_nothing_written(service_db)


def test_a4_three_open_orders_same_phone_digits_rejected(client, service_db):
    _setup(service_db)
    _open_orders(service_db, ["995555123456", "+995 (555) 123456", "995-555-12-34-56"])
    res = client.post("/orders", json=_order([1], phone=VALID_PHONE))
    assert res.status_code == 429, res.text
    assert res.json()["detail"] == PHONE_CAP_MSG
    _assert_nothing_written(service_db)
    q = service_db.calls_for("orders", "select")[0]
    assert ("eq", "shop_id", SHOP_ID) in q.filters
    assert ("eq", "status", "new") in q.filters
    assert any(f[0] == "gte" and f[1] == "created_at" for f in q.filters)


def test_a5_two_open_orders_proceed(client, service_db):
    _setup(service_db)
    _open_orders(service_db, ["995555123456", "+995 555 12-34-56", "599000000"])
    res = client.post("/orders", json=_order([1], phone=VALID_PHONE))
    assert res.status_code == 201, res.text
    assert service_db.rpc_calls == []
    inserts = service_db.calls_for("orders", "insert")
    assert len(inserts) == 1
    assert "website" not in inserts[0].payload
    assert "form_ms" not in inserts[0].payload
