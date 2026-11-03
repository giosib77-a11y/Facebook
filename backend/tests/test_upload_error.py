"""A-023 (N-14): Storage error text must not reach the client; it is logged server-side."""
import logging

import pytest

from app.core import ratelimit

SHOP = "22222222-2222-2222-2222-222222222222"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
RAW_ERROR = (
    '{"statusCode": "403", "error": "Unauthorized", '
    '"message": "new row violates row-level security policy"}'
)
FIXED_DETAIL = "ფოტოს ატვირთვა ვერ მოხერხდა — სცადეთ ცოტა ხანში."


class FailingBucket:
    def list(self, path=None, options=None):
        return []

    def upload(self, path, content, options=None):
        raise Exception(RAW_ERROR)

    def get_public_url(self, path):
        return f"https://proj.supabase.co/storage/v1/object/public/product-images/{path}"


class FailingStorage:
    def from_(self, bucket):
        return FailingBucket()


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    ratelimit._HITS.clear()
    yield
    ratelimit._HITS.clear()


def _upload(client):
    return client.post(
        "/products/upload-image",
        data={"shop_id": SHOP},
        files={"file": ("a.png", PNG, "image/png")},
    )


def test_storage_error_text_is_not_returned(client, user_db, service_db, caplog):
    user_db.responses[("shops", "select")] = [{"id": SHOP}]
    service_db.storage = FailingStorage()

    with caplog.at_level(logging.WARNING, logger="app"):
        r = _upload(client)

    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail == FIXED_DETAIL
    assert "statusCode" not in detail
    assert "row-level" not in detail
    assert "Unauthorized" not in r.text

    records = [rec for rec in caplog.records if "product image upload failed" in rec.getMessage()]
    assert len(records) == 1
    rec = records[0]
    assert SHOP in rec.getMessage()
    assert rec.exc_info is not None
    # the raw error is kept for the server log (via exc_info), not for the client
    assert RAW_ERROR in str(rec.exc_info[1])
