"""A-001: Excel/CSV re-upload must not zero price / quantity / sku of existing products."""
import uuid

import pytest

import app.api.products
from app.services.import_products import parse_products_file

SHOP_ID = str(uuid.uuid4())
PID = str(uuid.uuid4())


@pytest.fixture
def import_env(monkeypatch, user_db):
    monkeypatch.setattr(app.api.products, "bulk_import_allowed", lambda tier: True)
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "business"}]
    user_db.responses[("products", "select")] = [{"id": PID, "sku": "SKU-1", "name": "Shirt"}]
    return user_db


def upload(client, csv_text, mapping=None):
    data = {"shop_id": SHOP_ID}
    if mapping is not None:
        data["mapping"] = mapping
    return client.post(
        "/products/import",
        data=data,
        files={"file": ("p.csv", csv_text.encode(), "text/csv")},
    )


def only_update(user_db):
    updates = user_db.calls_for("products", "update")
    assert len(updates) == 1
    assert ("eq", "id", PID) in updates[0].filters
    return updates[0].payload


# ── parser: "unknown" is None, not 0 ──

def test_parser_returns_none_for_missing_columns():
    products, errors = parse_products_file(b"name,quantity\nShirt,5\n", "a.csv")
    assert errors == []
    assert products[0]["price"] is None and products[0]["sku"] is None
    assert products[0]["quantity"] == 5


def test_parser_returns_none_for_empty_cells_and_keeps_explicit_zero():
    products, _ = parse_products_file(b"name,price,qty,sku\nA,,,\nB,0,0,X\n", "a.csv")
    assert (products[0]["price"], products[0]["quantity"], products[0]["sku"]) == (None, None, None)
    assert (products[1]["price"], products[1]["quantity"], products[1]["sku"]) == (0.0, 0, "X")


# ── update path ──

def test_name_and_stock_only_keeps_price_and_sku(client, import_env):
    r = upload(client, "name,qty\nShirt,7\n")
    assert r.status_code == 200 and r.json()["updated"] == 1
    assert only_update(import_env) == {"name": "Shirt", "quantity": 7}


def test_name_and_price_only_keeps_stock_and_sku(client, import_env):
    r = upload(client, "name,price\nShirt,19.5\n")
    assert r.status_code == 200 and r.json()["updated"] == 1
    assert only_update(import_env) == {"name": "Shirt", "price": 19.5}


def test_empty_cell_in_mapped_column_keeps_existing_value(client, import_env):
    r = upload(client, "name,price,qty,sku\nShirt,,3,\n")
    assert r.status_code == 200
    assert only_update(import_env) == {"name": "Shirt", "quantity": 3}


def test_explicit_nonempty_values_update_all_fields(client, import_env):
    r = upload(client, "name,price,qty,sku\nShirt,25,0,SKU-1\n")
    assert r.status_code == 200
    # explicit 0 in the file is a real value and must be written
    assert only_update(import_env) == {"name": "Shirt", "price": 25.0, "quantity": 0, "sku": "SKU-1"}


def test_partial_mapping_override_keeps_price(client, import_env):
    r = upload(client, "title,amount\nShirt,9\n", mapping='{"name": 0, "quantity": 1}')
    assert r.status_code == 200
    assert only_update(import_env) == {"name": "Shirt", "quantity": 9}


# ── insert path: new products still default to 0 ──

def test_new_product_gets_zero_defaults_on_insert(client, import_env, service_db):
    r = upload(client, "name\nHat\n")
    assert r.status_code == 200 and r.json()["updated"] == 0
    inserts = service_db.calls_for("products", "insert")
    assert len(inserts) == 1
    row = inserts[0].payload[0]
    assert row["name"] == "Hat" and row["shop_id"] == SHOP_ID
    assert row["price"] == 0.0 and row["quantity"] == 0 and row["sku"] is None
    assert import_env.calls_for("products", "update") == []
