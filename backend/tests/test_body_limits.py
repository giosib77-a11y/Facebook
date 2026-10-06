"""FA-07 / FA-08: request bodies are size-bounded before reaching handlers."""
import inspect
import json

import pytest

import app.api.products
import app.api.shops
from app.core import ratelimit

TOO_LARGE = {"detail": "მოთხოვნა ძალიან დიდია"}
KiB = 1024


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    ratelimit._HITS.clear()
    yield
    ratelimit._HITS.clear()


def test_b1_declared_content_length_over_limit_rejected(client, service_db):
    body = json.dumps({"shop_id": "x", "pad": "a" * (300 * KiB)}).encode()
    r = client.post("/orders", content=body, headers={"Content-Type": "application/json"})
    assert r.request.headers["content-length"] == str(len(body))
    assert r.status_code == 413 and r.json() == TOO_LARGE
    assert service_db.calls == []


def test_b2_chunked_body_over_limit_rejected(client, service_db):
    def chunks():
        for _ in range(300):
            yield b"a" * KiB

    r = client.post("/orders", content=chunks(), headers={"Content-Type": "application/json"})
    assert "content-length" not in r.request.headers
    assert r.status_code == 413 and r.json() == TOO_LARGE
    assert service_db.calls == []


def test_b3_webhook_over_limit_rejected_before_signature_check(client):
    r = client.post(
        "/webhook",
        content=b"a" * (2 * 1024 * KiB),
        headers={"X-Hub-Signature-256": "sha256=bogus"},
    )
    assert r.status_code == 413 and r.json() == TOO_LARGE


def test_b4_small_order_not_affected(client, service_db):
    r = client.post("/orders", json={"shop_id": "22222222-2222-2222-2222-222222222222"})
    assert r.status_code != 413


def test_b5_upload_handlers_are_sync():
    for handler in (
        app.api.products.upload_product_image,
        app.api.products.import_preview,
        app.api.products.import_products,
        app.api.shops.upload_knowledge,
    ):
        assert not inspect.iscoroutinefunction(handler), handler.__name__
