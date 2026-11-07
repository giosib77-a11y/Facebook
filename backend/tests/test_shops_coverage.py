"""Stage 23 (A-049): behaviour tests for the paths of `api/shops.py` the other shop tests leave uncovered
(coverage gate >= 85% per file in CI). Offline (FakeSupabase, tests/conftest.py fixtures); nothing leaves the process.

Covered here: PATCH /shops/{id} (bot language), GET usage (404, pending-table failure, subscription expiry),
upgrade-request (insert failure), downgrade-free (404, pending-cancel failure), export 404, analytics,
clear-knowledge 404 on an empty write, `_cancel_pending_requests([])`.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import app.api.shops as shops_mod
from app.core.db import SCHEMA_ERROR_DETAIL
from app.main import app as fastapi_app

SHOP_ID = "22222222-2222-2222-2222-222222222222"
NOT_FOUND = "მაღაზია ვერ მოიძებნა ან არ არის თქვენი"


def _api_error(code, message="boom"):
    return APIError({"message": message, "code": code, "hint": None, "details": None})


def _owner(user_db, tier=None):
    row = {"id": SHOP_ID}
    if tier is not None:
        row["subscription_tier"] = tier
    user_db.responses[("shops", "select")] = [row]


# ---- _cancel_pending_requests ------------------------------------------------------------------
def test_cancel_pending_requests_with_no_shops_makes_no_db_call(service_db):
    assert shops_mod._cancel_pending_requests([]) is None
    assert service_db.calls == []


def test_cancel_pending_requests_cancels_only_pending_of_given_shops(service_db):
    shops_mod._cancel_pending_requests([SHOP_ID])
    (c,) = service_db.calls_for("upgrade_requests", "update")
    assert c.payload == {"status": "cancelled"}
    assert ("in", "shop_id", [SHOP_ID]) in c.filters
    assert ("eq", "status", "pending") in c.filters


# ---- PATCH /shops/{id} -------------------------------------------------------------------------
@pytest.mark.parametrize("lang", ["auto", "ka", "en", "ru"])
def test_patch_shop_sets_supported_bot_language_with_user_client(client, user_db, service_db, lang):
    user_db.responses[("shops", "update")] = [{
        "id": SHOP_ID, "owner_id": "11111111-1111-1111-1111-111111111111", "name": "S", "currency": "GEL",
        "bot_enabled": True, "bot_language": lang,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        "facebook_page_token": "secret-page-token",  # not in ShopOut -> must not reach the response
    }]
    r = client.patch(f"/shops/{SHOP_ID}", json={"bot_language": lang})
    assert r.status_code == 200 and r.json()["bot_language"] == lang
    assert "facebook_page_token" not in r.json() and "secret-page-token" not in r.text
    (u,) = user_db.calls_for("shops", "update")
    assert u.payload == {"bot_language": lang}  # nothing else can be written through this endpoint
    assert ("eq", "id", SHOP_ID) in u.filters
    assert service_db.calls == []  # RLS client only


@pytest.mark.parametrize("lang", ["de", "", "KA", "ka "])
def test_patch_shop_rejects_unsupported_language_without_db_call(client, user_db, service_db, lang):
    r = client.patch(f"/shops/{SHOP_ID}", json={"bot_language": lang})
    assert r.status_code == 400 and r.json()["detail"] == "არასწორი ენა"
    assert user_db.calls == [] and service_db.calls == []


def test_patch_shop_not_owned_is_404(client, user_db, service_db):
    user_db.responses[("shops", "update")] = []  # RLS hides the row -> nothing updated
    r = client.patch(f"/shops/{SHOP_ID}", json={"bot_language": "ka"})
    assert r.status_code == 404 and r.json()["detail"] == NOT_FOUND
    assert service_db.calls == []


def test_patch_shop_rls_denial_is_403(client, user_db):
    user_db.errors[("shops", "update")] = _api_error("42501")
    r = client.patch(f"/shops/{SHOP_ID}", json={"bot_language": "ka"})
    assert r.status_code == 403
    assert r.json()["detail"] == "წვდომა აკრძალულია: ეს რესურსი თქვენი არ არის (RLS)"


def test_patch_shop_validates_body_and_path(client, user_db):
    assert client.patch(f"/shops/{SHOP_ID}", json={}).status_code == 422
    assert client.patch("/shops/not-a-uuid", json={"bot_language": "ka"}).status_code == 422
    assert user_db.calls == []


# ---- GET /shops/{id}/usage ---------------------------------------------------------------------
def test_usage_unknown_shop_is_404_and_counts_nothing(client, user_db):
    r = client.get(f"/shops/{SHOP_ID}/usage")
    assert r.status_code == 404 and r.json()["detail"] == NOT_FOUND
    assert [c.table for c in user_db.calls] == ["shops"]  # no customer / product / request queries


def test_usage_survives_upgrade_requests_table_failure(client, user_db):
    _owner(user_db, "free")
    user_db.counts[("bot_customers", "select")] = 7
    user_db.counts[("products", "select")] = 3
    user_db.errors[("upgrade_requests", "select")] = RuntimeError("relation does not exist")
    r = client.get(f"/shops/{SHOP_ID}/usage")
    assert r.status_code == 200
    body = r.json()
    assert body["pending_request"] is None
    assert body["tier"] == "free" and body["monthly_customers"] == 7 and body["products"] == 3


def test_usage_reports_pending_request(client, user_db):
    _owner(user_db, "free")
    user_db.responses[("upgrade_requests", "select")] = [{"requested_tier": "standard"}]
    assert client.get(f"/shops/{SHOP_ID}/usage").json()["pending_request"] == "standard"


def _usage_with_paid_until(client, user_db, delta):
    _owner(user_db, "standard")
    until = datetime.now(timezone.utc) + delta
    user_db.responses[("subscriptions", "select")] = [{"tier": "standard", "paid_until": until.isoformat()}]
    r = client.get(f"/shops/{SHOP_ID}/usage")
    assert r.status_code == 200
    return r.json(), until


def test_usage_subscription_expired(client, user_db):
    body, until = _usage_with_paid_until(client, user_db, timedelta(days=-1))
    assert body["tier"] == "standard"
    assert body["expired"] is True and body["expires_soon"] is False
    assert body["paid_until"] == until.isoformat()


def test_usage_subscription_expires_soon(client, user_db):
    body, _ = _usage_with_paid_until(client, user_db, timedelta(days=2))
    assert body["expires_soon"] is True and body["expired"] is False


def test_usage_subscription_far_in_future(client, user_db):
    body, _ = _usage_with_paid_until(client, user_db, timedelta(days=20))
    assert body["expires_soon"] is False and body["expired"] is False


@pytest.mark.parametrize("exc, status_code, body", [
    (_api_error("PGRST205", "Could not find the table"), 503, {"detail": SCHEMA_ERROR_DETAIL}),
    (RuntimeError("relation \"subscriptions\" does not exist"), 500, None),
])
def test_usage_subscriptions_read_error_is_503_for_schema_and_500_otherwise(
    client, user_db, exc, status_code, body
):
    _owner(user_db, "standard")
    user_db.errors[("subscriptions", "select")] = exc
    r = TestClient(fastapi_app, raise_server_exceptions=False).get(f"/shops/{SHOP_ID}/usage")
    assert r.status_code == status_code, r.text  # old code: 200 with `paid_until: null`
    if body is not None:
        assert r.json() == body
    assert "paid_until" not in r.json()


def test_usage_free_tier_never_reads_subscriptions(client, user_db):
    _owner(user_db, "free")
    user_db.responses[("subscriptions", "select")] = [{"tier": "free", "paid_until": "2000-01-01T00:00:00+00:00"}]
    body = client.get(f"/shops/{SHOP_ID}/usage").json()
    assert user_db.calls_for("subscriptions", "select") == []
    assert body["paid_until"] is None and body["expired"] is False


# ---- POST /shops/{id}/upgrade-request ----------------------------------------------------------
def test_upgrade_request_insert_denied_by_db_keeps_http_error(client, user_db, service_db):
    _owner(user_db)
    service_db.errors[("upgrade_requests", "insert")] = _api_error("42501")
    r = client.post(f"/shops/{SHOP_ID}/upgrade-request", json={"tier": "standard"})
    # the HTTPException from core.db.run is re-raised as is (not wrapped into the generic 500)
    assert r.status_code == 403
    assert r.json()["detail"] == "წვდომა აკრძალულია: ეს რესურსი თქვენი არ არის (RLS)"
    assert len(service_db.calls_for("upgrade_requests", "insert")) == 1


def test_upgrade_request_invalid_tier_is_400_without_db_call(client, user_db, service_db):
    for tier in ("free", "platinum", ""):
        r = client.post(f"/shops/{SHOP_ID}/upgrade-request", json={"tier": tier})
        assert r.status_code == 400 and r.json()["detail"] == "არასწორი პაკეტი"
    assert user_db.calls == [] and service_db.calls == []


# ---- POST /shops/{id}/downgrade-free -----------------------------------------------------------
def test_downgrade_without_any_shop_is_404_and_changes_nothing_else(client, service_db):
    service_db.responses[("shops", "update")] = []
    r = client.post(f"/shops/{SHOP_ID}/downgrade-free")
    assert r.status_code == 404 and r.json()["detail"] == NOT_FOUND
    # only the (empty) tier update ran: no subscription row, no request cancel, no bot limit pass
    assert [(c.table, c.op) for c in service_db.calls] == [("shops", "update")]
    (u,) = service_db.calls
    assert u.payload == {"subscription_tier": "free"}
    assert ("eq", "owner_id", "11111111-1111-1111-1111-111111111111") in u.filters


def test_downgrade_pending_cancel_failure_is_500_after_tier_change(client, service_db):
    service_db.responses[("shops", "update")] = [{"id": SHOP_ID}]
    service_db.errors[("upgrade_requests", "update")] = RuntimeError("db down")
    r = client.post(f"/shops/{SHOP_ID}/downgrade-free")
    assert r.status_code == 500
    assert r.json()["detail"] == "პაკეტი შეიცვალა, მაგრამ მოთხოვნების გაუქმება ვერ მოხერხდა — სცადე ხელახლა."
    assert "db down" not in r.text
    (sub,) = service_db.calls_for("subscriptions", "upsert")  # tier is already free, so the expiry row is too
    assert sub.payload["tier"] == "free" and sub.payload["paid_until"] is None
    assert service_db.calls_for("shops", "select") == []  # bot-limit pass not reached
    assert service_db.calls_for("shops", "update")[0].payload == {"subscription_tier": "free"}


# ---- GET /shops/{id}/export --------------------------------------------------------------------
def test_export_not_owned_is_404_and_reads_no_data(client, user_db):
    r = client.get(f"/shops/{SHOP_ID}/export")
    assert r.status_code == 404 and r.json()["detail"] == NOT_FOUND
    assert [c.table for c in user_db.calls] == ["shops"]  # products / orders never queried


# ---- GET /shops/{id}/analytics -----------------------------------------------------------------
def test_analytics_not_owned_is_404_and_reads_no_conversations(client, user_db):
    r = client.get(f"/shops/{SHOP_ID}/analytics")
    assert r.status_code == 404 and r.json()["detail"] == NOT_FOUND
    assert user_db.calls_for("bot_conversations", "select") == []


def test_analytics_without_migration_returns_empty_stats(client, user_db):
    _owner(user_db)
    user_db.errors[("bot_conversations", "select")] = RuntimeError("relation does not exist")
    r = client.get(f"/shops/{SHOP_ID}/analytics")
    assert r.status_code == 200
    assert r.json() == {"total_conversations": 0, "needs_attention": 0, "top_terms": [], "recent_questions": []}


def test_analytics_no_conversations_is_empty_stats(client, user_db):
    _owner(user_db)
    r = client.get(f"/shops/{SHOP_ID}/analytics")
    assert r.status_code == 200
    assert r.json() == {"total_conversations": 0, "needs_attention": 0, "top_terms": [], "recent_questions": []}


def test_analytics_counts_terms_and_attention_from_user_messages_only(client, user_db):
    _owner(user_db)
    user_db.responses[("bot_conversations", "select")] = [
        {
            "needs_attention": False,
            "messages": [
                {"role": "user", "content": "მინდა ქურთუკი"},
                {"role": "assistant", "content": "ქურთუკი ხელმისაწვდომია"},  # bot text is not a question
                {"role": "user", "content": "[სურათი]"},  # image placeholder is skipped
                {"role": "user", "content": "   "},
                {"role": "user", "content": None},
            ],
        },
        {
            "needs_attention": True,
            "messages": [
                {"role": "user", "content": "ქურთუკი ღირს? Shoes"},
                {"role": "user", "content": "SHOES size 42"},
            ],
        },
        {"needs_attention": False, "messages": None},
    ]
    r = client.get(f"/shops/{SHOP_ID}/analytics")
    assert r.status_code == 200
    body = r.json()
    assert body["total_conversations"] == 3
    assert body["needs_attention"] == 1
    # stopwords (მინდა, ღირს) and tokens shorter than 3 chars (42) are not topics; matching is case-insensitive
    assert body["top_terms"] == [
        {"term": "ქურთუკი", "count": 2},
        {"term": "shoes", "count": 2},
        {"term": "size", "count": 1},
    ]
    assert body["recent_questions"] == ["მინდა ქურთუკი", "ქურთუკი ღირს? Shoes", "SHOES size 42"]
    (q,) = user_db.calls_for("bot_conversations", "select")
    assert ("eq", "shop_id", SHOP_ID) in q.filters
    assert q.orders == [("updated_at", True)]


def test_analytics_caps_top_terms_at_12_and_recent_questions_at_25(client, user_db):
    _owner(user_db)
    user_db.responses[("bot_conversations", "select")] = [
        {"needs_attention": False, "messages": [{"role": "user", "content": f"term{chr(97 + i)}x"}]}
        for i in range(30)
    ]
    body = client.get(f"/shops/{SHOP_ID}/analytics").json()
    assert body["total_conversations"] == 30
    assert len(body["top_terms"]) == 12
    assert body["recent_questions"] == [f"term{chr(97 + i)}x" for i in range(25)]


# ---- DELETE /shops/{id}/knowledge --------------------------------------------------------------
def test_clear_knowledge_empty_write_is_404(client, user_db, service_db):
    _owner(user_db)
    service_db.responses[("shops", "update")] = []  # the row vanished between the RLS check and the write
    r = client.delete(f"/shops/{SHOP_ID}/knowledge")
    assert r.status_code == 404 and r.json()["detail"] == NOT_FOUND
    (u,) = service_db.calls_for("shops", "update")
    assert u.payload == {"knowledge": None, "knowledge_filename": None, "knowledge_faq": None}
    assert ("eq", "id", SHOP_ID) in u.filters


def test_clear_knowledge_not_owned_is_404_without_service_write(client, user_db, service_db):
    r = client.delete(f"/shops/{SHOP_ID}/knowledge")
    assert r.status_code == 404 and r.json()["detail"] == NOT_FOUND
    assert service_db.calls == []
