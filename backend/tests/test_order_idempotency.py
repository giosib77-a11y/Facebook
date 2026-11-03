"""A-020: repeating the same POST /orders (same idempotency_key) must not create a second order."""
import re
from pathlib import Path

from postgrest.exceptions import APIError

SHOP_ID = "22222222-2222-2222-2222-222222222222"
PRODUCT_ID = "33333333-3333-3333-3333-333333333333"
ORDER_ID = "44444444-4444-4444-4444-444444444444"
KEY = "55555555-5555-4555-8555-555555555555"
MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0031_orders_idempotency_key.sql"


def _setup(db):
    db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    db.responses[("products", "select")] = [
        {"id": PRODUCT_ID, "name": "Test Product", "price": 5, "quantity": 100}
    ]
    db.counts[("orders", "select")] = 0
    db.responses[("orders", "insert")] = [{"id": ORDER_ID}]


def _order(key=KEY):
    body = {
        "shop_id": SHOP_ID,
        "customer_name": "Buyer",
        "customer_phone": "+995 555 12-34-56",
        "items": [{"product_id": PRODUCT_ID, "name": "x", "quantity": 2}],
        "form_ms": 5000,
    }
    if key is not None:
        body["idempotency_key"] = key
    return body


def _key_lookups(db):
    return [
        q for q in db.calls_for("orders", "select")
        if ("eq", "idempotency_key", KEY) in q.filters
    ]


def test_retry_with_same_key_returns_first_order_without_second_insert(client, service_db):
    _setup(service_db)
    first = client.post("/orders", json=_order())
    assert first.status_code == 201
    (ins,) = service_db.calls_for("orders", "insert")
    assert ins.payload["idempotency_key"] == KEY

    # the first order is now stored under this key
    service_db.responses[("orders", "select")] = [{"id": ORDER_ID, "total": 10.0}]
    second = client.post("/orders", json=_order())
    assert second.status_code == 201
    assert second.json() == first.json() == {"ok": True, "order_id": ORDER_ID, "total": 10.0}
    assert len(service_db.calls_for("orders", "insert")) == 1
    lookup = _key_lookups(service_db)[-1]
    assert ("eq", "shop_id", SHOP_ID) in lookup.filters  # key is scoped to the shop


def test_concurrent_duplicate_unique_violation_returns_existing_order(client, service_db):
    _setup(service_db)
    service_db.errors[("orders", "insert")] = APIError(
        {"code": "23505", "message": "duplicate key value violates unique constraint "
         "\"orders_shop_idempotency_key_uniq\""}
    )

    class _Responses(dict):
        """orders select: empty before the (losing) INSERT, the winner's row after it."""

        def get(self, k, default=None):
            if k == ("orders", "select") and service_db.calls_for("orders", "insert"):
                return [{"id": ORDER_ID, "total": 10.0}]
            return super().get(k, default)

    service_db.responses = _Responses(service_db.responses)
    r = client.post("/orders", json=_order())
    assert r.status_code == 201
    assert r.json()["order_id"] == ORDER_ID
    assert len(service_db.calls_for("orders", "insert")) == 1


def test_without_key_behaves_as_before(client, service_db):
    _setup(service_db)
    r = client.post("/orders", json=_order(key=None))
    assert r.status_code == 201
    (ins,) = service_db.calls_for("orders", "insert")
    assert "idempotency_key" not in ins.payload
    assert _key_lookups(service_db) == []


def test_missing_column_falls_back_to_plain_insert(client, service_db, caplog, monkeypatch):
    """migration 0031 not applied: the lookup fails → order is still created, without the key."""
    FakeQuery = type(service_db.table("orders"))  # the conftest class pytest actually loaded
    _setup(service_db)
    real_execute = FakeQuery.execute

    def execute(self):
        if self.table == "orders" and ("eq", "idempotency_key", KEY) in self.filters:
            raise APIError({"code": "42703", "message": "column orders.idempotency_key does not exist"})
        return real_execute(self)

    monkeypatch.setattr(FakeQuery, "execute", execute)
    r = client.post("/orders", json=_order())
    assert r.status_code == 201
    (ins,) = service_db.calls_for("orders", "insert")
    assert "idempotency_key" not in ins.payload
    assert "idempotency" in caplog.text


def test_invalid_key_rejected(client, service_db):
    _setup(service_db)
    r = client.post("/orders", json=_order(key="not-a-uuid"))
    assert r.status_code == 422
    assert service_db.calls_for("orders", "insert") == []


def _code(sql: str) -> str:
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def test_migration_0031_adds_key_and_partial_unique_index():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "alter table public.orders add column if not exists idempotency_key uuid;" in code
    assert (
        "create unique index if not exists orders_shop_idempotency_key_uniq on public.orders "
        "(shop_id, idempotency_key) where idempotency_key is not null;"
    ) in code
    for forbidden in ("grant", "revoke", "create policy", "drop", "delete from", "update public."):
        assert forbidden not in code, forbidden
