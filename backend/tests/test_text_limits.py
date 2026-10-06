"""FA-01: seller/customer-controlled text is bounded in the API models and the bot prompt."""
import uuid

import pytest
from pydantic import ValidationError

from app.models.order import OrderCreate
from app.models.product import ProductCreate
from app.services.bot import build_system_prompt
from app.services.import_products import parse_products_file

SHOP_ID = str(uuid.uuid4())


def test_prompt_is_bounded_regardless_of_db_contents():
    huge = "x" * 100_000
    shop = {
        "id": SHOP_ID,
        "name": "Shop",
        "description": "d" * 1_000_000,
        "knowledge": "k" * 1_000_000,
        "currency": "GEL",
    }
    products = [
        {"name": huge, "sku": huge, "description": huge, "price": 10, "quantity": 1}
        for _ in range(30)
    ]
    prompt = build_system_prompt(shop, products)
    assert len(prompt) < 100_000


def test_product_description_cap():
    ProductCreate(shop_id=SHOP_ID, name="p", description="a" * 5000)
    with pytest.raises(ValidationError):
        ProductCreate(shop_id=SHOP_ID, name="p", description="a" * 5001)


def _item():
    return {"name": "p", "price": 1, "quantity": 1}


def test_order_note_cap():
    with pytest.raises(ValidationError):
        OrderCreate(shop_id=SHOP_ID, customer_name="c", note="n" * 1001, items=[_item()])


def test_order_items_cap():
    with pytest.raises(ValidationError):
        OrderCreate(shop_id=SHOP_ID, customer_name="c", items=[_item() for _ in range(101)])


def test_import_rejects_overlong_description():
    csv_bytes = ("name,price,description\nItem,5," + "d" * 5001 + "\n").encode("utf-8")
    products, errors = parse_products_file(csv_bytes, "products.csv")
    assert products == []
    assert [e["row"] for e in errors] == [2]
