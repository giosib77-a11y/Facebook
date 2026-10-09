"""Price/quantity validation: NaN/Infinity rejected in API models and file import."""
import uuid

import pytest
from pydantic import ValidationError

from app.models.order import OrderItem
from app.models.product import ProductCreate, ProductUpdate
from app.services.import_products import parse_products_file

SHOP_ID = uuid.uuid4()


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), "Infinity", "NaN"])
def test_models_reject_non_finite_price(bad):
    with pytest.raises(ValidationError):
        ProductCreate(shop_id=SHOP_ID, name="p", price=bad)
    with pytest.raises(ValidationError):
        ProductUpdate(price=bad)
    with pytest.raises(ValidationError):
        OrderItem(name="p", price=bad, quantity=1)


def test_models_json_overflow_price_rejected():
    body = '{"shop_id": "%s", "name": "x", "price": 1e999}' % SHOP_ID
    with pytest.raises(ValidationError):
        ProductCreate.model_validate_json(body)


def _parse(price, qty):
    return parse_products_file(f"name,price,qty\nA,{price},{qty}\n".encode(), "a.csv")


@pytest.mark.parametrize("price", ["nan", "inf", "-inf", "1e999"])
def test_import_rejects_non_finite_price(price):
    products, errors = _parse(price, "1")
    assert products == []
    assert errors[0]["row"] == 2


@pytest.mark.parametrize("qty", ["2.5", "0.5", "inf", "nan", "1e400"])
def test_import_rejects_non_integer_quantity_with_row(qty):
    products, errors = _parse("5", qty)
    assert products == []
    assert errors[0]["row"] == 2
    assert "მარაგი" in errors[0]["message"]


@pytest.mark.parametrize("qty", ["3", "3.0"])
def test_import_accepts_whole_quantity(qty):
    products, errors = _parse("5.5", qty)
    assert errors == []
    assert products[0]["quantity"] == 3
