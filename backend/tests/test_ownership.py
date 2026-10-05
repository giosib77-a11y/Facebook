"""Ownership guards on service_role writes (commit 0643e64, F-01/F-02).

These endpoints write through get_service_client() (RLS bypassed), so each one
must verify ownership itself. The tests pin that behavior.
"""
from tests.conftest import USER_ID

SHOP_ID = "22222222-2222-2222-2222-222222222222"
OTHER_SHOP_ID = "33333333-3333-3333-3333-333333333333"

PRODUCT_PAYLOAD = {"shop_id": SHOP_ID, "name": "Test product", "price": 10}
TIMESTAMPS = {"created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}


def test_create_product_rejects_shop_not_owned(client, user_db, service_db):
    """სხვისი მაღაზია (RLS select ცარიელია) → 404 და service_role insert არ ხდება."""
    user_db.responses[("shops", "select")] = []

    resp = client.post("/products", json=PRODUCT_PAYLOAD)

    assert resp.status_code == 404
    assert service_db.calls_for("products", "insert") == []


def test_create_product_inserts_via_service_client_for_owned_shop(client, user_db, service_db):
    """საკუთარი მაღაზია → ერთი insert service client-ით, სწორი shop_id-ით; user client არ წერს."""
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "business"}]
    service_db.responses[("products", "insert")] = [
        {
            "id": "44444444-4444-4444-4444-444444444444",
            **PRODUCT_PAYLOAD,
            "quantity": 0,
            "is_active": True,
            **TIMESTAMPS,
        }
    ]

    resp = client.post("/products", json=PRODUCT_PAYLOAD)

    assert resp.status_code == 201, resp.text
    inserts = service_db.calls_for("products", "insert")
    assert len(inserts) == 1
    assert inserts[0].payload["shop_id"] == SHOP_ID
    assert user_db.calls_for("products", "insert") == []


def test_create_shop_sets_owner_and_inherits_best_tier(client, user_db, service_db):
    """ახალი მაღაზია → service insert owner_id=auth user-ით და მფლობელის საუკეთესო პაკეტით."""
    user_db.responses[("shops", "select")] = [{"subscription_tier": "standard"}]
    service_db.responses[("shops", "insert")] = [
        {
            "id": SHOP_ID,
            "owner_id": USER_ID,
            "name": "New shop",
            "subscription_tier": "standard",
            "currency": "GEL",
            "bot_enabled": True,
            **TIMESTAMPS,
        }
    ]

    resp = client.post("/shops", json={"name": "New shop"})

    assert resp.status_code == 201, resp.text
    inserts = service_db.calls_for("shops", "insert")
    assert len(inserts) == 1
    assert inserts[0].payload["owner_id"] == USER_ID
    assert inserts[0].payload["subscription_tier"] == "standard"
    assert user_db.calls_for("shops", "insert") == []


def test_facebook_disconnect_rejects_shop_not_owned(client, user_db, service_db):
    """სხვისი მაღაზიის გათიშვა → 404 და service_role update არ ხდება."""
    user_db.responses[("shops", "select")] = []

    resp = client.post("/facebook/disconnect", params={"shop_id": SHOP_ID})

    assert resp.status_code == 404
    assert service_db.calls_for("shops", "update") == []


def test_downgrade_filters_every_shop_update_by_owner(client, service_db):
    """downgrade → service client-ის ყველა shops update გაფილტრულია owner_id = auth user-ით."""
    # Two shops with bots on → both the tier update and the excess-bot disable run.
    service_db.responses[("shops", "update")] = [
        {"id": SHOP_ID, "name": "A", "bot_enabled": True, "created_at": "2026-01-01"},
        {"id": OTHER_SHOP_ID, "name": "B", "bot_enabled": True, "created_at": "2026-02-01"},
    ]

    resp = client.post(f"/shops/{SHOP_ID}/downgrade-free")

    assert resp.status_code == 200, resp.text
    updates = service_db.calls_for("shops", "update")
    assert len(updates) == 2
    for update in updates:
        assert ("eq", "owner_id", USER_ID) in update.filters
