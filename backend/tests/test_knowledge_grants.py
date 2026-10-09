"""S11-5: knowledge writes go through the service client after an RLS ownership check."""
import uuid

import pytest

import app.api.shops
from conftest import USER_ID

TIMESTAMPS = {"created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}
SHOP_ID = str(uuid.uuid4())
URL = f"/shops/{SHOP_ID}/knowledge"

def shop_row(**extra):
    return {"id": SHOP_ID, "owner_id": USER_ID, "name": "S", "currency": "GEL",
            "bot_enabled": True, **TIMESTAMPS, **extra}


PDF = {"file": ("k.pdf", b"%PDF-1.4", "application/pdf")}


@pytest.fixture(autouse=True)
def _fake_pdf(monkeypatch):
    monkeypatch.setattr(app.api.shops, "extract_pdf_text", lambda content: "extracted")


def test_upload_foreign_shop_404_no_write(client, user_db, service_db):
    user_db.responses[("shops", "select")] = []  # RLS hides other user's shop
    r = client.post(URL, files=PDF)
    assert r.status_code == 404
    assert service_db.calls_for("shops", "update") == []
    assert user_db.calls_for("shops", "update") == []


def test_upload_owner_writes_via_service_client(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "standard"}]
    service_db.responses[("shops", "update")] = [shop_row(knowledge_filename="k.pdf")]
    r = client.post(URL, files=PDF)
    assert r.status_code == 200
    updates = service_db.calls_for("shops", "update")
    assert len(updates) == 1
    assert updates[0].payload == {"knowledge": "extracted", "knowledge_filename": "k.pdf"}
    assert user_db.calls_for("shops", "update") == []


def test_upload_free_tier_403_no_write(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "free"}]
    r = client.post(URL, files=PDF)
    assert r.status_code == 403
    assert service_db.calls_for("shops", "update") == []


def test_upload_service_write_empty_is_404(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "standard"}]
    service_db.responses[("shops", "update")] = []
    assert client.post(URL, files=PDF).status_code == 404


def test_clear_foreign_shop_404_no_write(client, user_db, service_db):
    user_db.responses[("shops", "select")] = []
    r = client.delete(URL)
    assert r.status_code == 404
    assert service_db.calls_for("shops", "update") == []
    assert user_db.calls_for("shops", "update") == []


def test_clear_owner_free_tier_writes_via_service_client(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID}]  # no tier gate on clear
    service_db.responses[("shops", "update")] = [shop_row()]
    r = client.delete(URL)
    assert r.status_code == 200
    updates = service_db.calls_for("shops", "update")
    assert len(updates) == 1
    assert updates[0].payload == {"knowledge": None, "knowledge_filename": None}
    assert user_db.calls_for("shops", "update") == []
