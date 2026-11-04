"""A-017: Meta Data Deletion callback records a real status; errors are not swallowed."""
import base64
import hashlib
import hmac
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.api.facebook as api_fb
from app.config import Settings
from app.services.facebook import GraphError

SECRET = "test-app-secret"
FB_USER = "1234567890"
SHOP_ID = "22222222-2222-2222-2222-222222222222"
TABLE = "data_deletion_requests"
MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0029_data_deletion_requests.sql"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    s = Settings(_env_file=None, fb_app_secret=SECRET, public_base_url="https://chatassist.test")
    monkeypatch.setattr(api_fb, "get_settings", lambda: s)


def _signed(payload: dict, secret: str = SECRET) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=") + "." + body


def _callback(client):
    return client.post("/facebook/data-deletion", data={"signed_request": _signed({"user_id": FB_USER})})


def _final_update(db) -> dict:
    updates = db.calls_for(TABLE, "update")
    assert len(updates) == 1
    return updates[0].payload


def test_success_records_pending_then_completed(client, service_db):
    service_db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    r = _callback(client)
    assert r.status_code == 200
    code = r.json()["confirmation_code"]
    assert r.json()["url"].endswith(f"/panel/delete-data.html?code={code}")

    (rec,) = service_db.calls_for(TABLE, "upsert")
    assert rec.payload == {"code": code, "fb_user_id": FB_USER, "status": "pending", "error": None}
    final = _final_update(service_db)
    assert final["status"] == "completed" and final["fb_user_id"] is None and final["error"] is None
    assert ("eq", "code", code) in service_db.calls_for(TABLE, "update")[0].filters
    # the actual erasure happened: the seller's shop conversations + page data (A-039: ASID, not PSID)
    (deleted,) = service_db.calls_for("bot_conversations", "delete")
    assert ("eq", "shop_id", SHOP_ID) in deleted.filters
    for call in service_db.calls:
        if call.op == "delete":
            assert not any(f[1] == "psid" for f in call.filters)
    update = service_db.calls_for("shops", "update")[0].payload
    assert update["facebook_page_token"] is None
    assert update["facebook_user_id"] is None


@pytest.mark.parametrize("table,op", [
    ("bot_conversations", "delete"),
    ("bot_customers", "delete"),
    ("shops", "select"),
    ("shops", "update"),
])
def test_erasure_error_is_recorded_as_failed(client, service_db, caplog, table, op):
    service_db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    service_db.errors[(table, op)] = RuntimeError("db down")
    r = _callback(client)
    assert r.status_code == 200 and r.json()["confirmation_code"]
    final = _final_update(service_db)
    assert final["status"] == "failed"
    assert final["error"] == "RuntimeError"
    assert "fb_user_id" not in final  # kept for a manual retry
    assert "data deletion failed" in caplog.text


def test_seller_shop_customer_counters_are_deleted(client, service_db):
    # A-039: bot_customers (per-customer monthly counters) of the seller's shop are erased by shop_id
    service_db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    r = _callback(client)
    assert r.status_code == 200
    (d,) = service_db.calls_for("bot_customers", "delete")
    assert ("eq", "shop_id", SHOP_ID) in d.filters
    assert not any(f[1] == "psid" for f in d.filters)
    assert _final_update(service_db)["status"] == "completed"


def test_bot_customers_delete_error_is_recorded_as_failed(client, service_db):
    service_db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    service_db.errors[("bot_customers", "delete")] = RuntimeError("db down")
    r = _callback(client)
    assert r.status_code == 200 and r.json()["confirmation_code"]
    final = _final_update(service_db)
    assert final["status"] == "failed" and final["error"] == "RuntimeError"
    assert "fb_user_id" not in final  # kept for a manual retry


PAGE_ID = "9876543210"
ENC_TOKEN = "enc-token-blob"
PLAIN_TOKEN = "EAAB-plain-page-token-xyz"
SHOP2_ID = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def graph(monkeypatch, service_db):
    """Fake decrypt + fake unsubscribe_page; records (page_id, token, db calls made so far)."""
    calls = []
    behaviour = {"error": None}

    def fake_unsubscribe(page_id, token):
        calls.append((page_id, token, [(c.table, c.op) for c in service_db.calls]))
        if behaviour["error"]:
            raise behaviour["error"]

    def fake_decrypt(value):
        if value != ENC_TOKEN:
            raise ValueError("cannot decrypt")
        return PLAIN_TOKEN

    monkeypatch.setattr(api_fb, "decrypt", fake_decrypt)
    monkeypatch.setattr(api_fb.fb, "unsubscribe_page", fake_unsubscribe)
    return SimpleNamespace(calls=calls, behaviour=behaviour)


def _page_shop(shop_id=SHOP_ID, token=ENC_TOKEN):
    return {"id": shop_id, "facebook_page_id": PAGE_ID, "facebook_page_token": token}


def test_unknown_asid_deletes_nothing_and_completes(client, service_db):
    # A-039: no shop with this facebook_user_id -> nothing to erase (never deletes by psid = ASID)
    r = _callback(client)
    assert r.status_code == 200
    assert service_db.calls_for("bot_conversations", "delete") == []
    assert service_db.calls_for("bot_customers", "delete") == []
    assert service_db.calls_for("shops", "update") == []
    (q,) = service_db.calls_for("shops", "select")
    assert ("eq", "facebook_user_id", FB_USER) in q.filters
    assert _final_update(service_db)["status"] == "completed"


def test_page_shop_is_unsubscribed_with_decrypted_token_before_clearing(client, service_db, graph):
    service_db.responses[("shops", "select")] = [_page_shop()]
    r = _callback(client)
    assert r.status_code == 200
    assert len(graph.calls) == 1
    page_id, token, seen = graph.calls[0]
    assert (page_id, token) == (PAGE_ID, PLAIN_TOKEN)
    assert ("shops", "update") not in seen  # the token is still in the row when Meta is told
    assert service_db.calls_for("shops", "update")[0].payload["facebook_page_token"] is None
    assert _final_update(service_db)["status"] == "completed"


def test_unsubscribe_graph_error_is_logged_without_token_and_still_completes(
    client, service_db, graph, caplog
):
    service_db.responses[("shops", "select")] = [_page_shop()]
    graph.behaviour["error"] = GraphError(400, f"Invalid token {PLAIN_TOKEN}")
    with caplog.at_level(logging.WARNING, logger="app"):
        r = _callback(client)
    assert r.status_code == 200
    assert _final_update(service_db)["status"] == "completed"
    assert "unsubscribe on data deletion failed" in caplog.text
    assert "GraphError" in caplog.text
    assert PLAIN_TOKEN not in caplog.text and ENC_TOKEN not in caplog.text and FB_USER not in caplog.text
    # erasure still went on after the failed Graph call
    assert len(service_db.calls_for("bot_conversations", "delete")) == 1
    assert service_db.calls_for("shops", "update")[0].payload["facebook_user_id"] is None


def test_decrypt_failure_skips_graph_and_still_completes(client, service_db, graph):
    service_db.responses[("shops", "select")] = [_page_shop(token="not-decryptable")]
    r = _callback(client)
    assert r.status_code == 200
    assert graph.calls == []
    assert _final_update(service_db)["status"] == "completed"
    assert len(service_db.calls_for("bot_customers", "delete")) == 1
    assert len(service_db.calls_for("shops", "update")) == 1


def test_shop_without_page_makes_no_graph_call(client, service_db, graph):
    service_db.responses[("shops", "select")] = [{"id": SHOP_ID, "facebook_page_id": None, "facebook_page_token": None}]
    assert _callback(client).status_code == 200
    assert graph.calls == []
    assert len(service_db.calls_for("shops", "update")) == 1


def test_all_shops_of_the_seller_are_processed(client, service_db, graph):
    service_db.responses[("shops", "select")] = [_page_shop(SHOP_ID), _page_shop(SHOP2_ID)]
    graph.behaviour["error"] = GraphError(None, "network error")  # first failure must not stop the second shop
    assert _callback(client).status_code == 200
    assert len(graph.calls) == 2
    for table in ("bot_conversations", "bot_customers"):
        ids = {f[2] for c in service_db.calls_for(table, "delete") for f in c.filters if f[1] == "shop_id"}
        assert ids == {SHOP_ID, SHOP2_ID}
    updated = {f[2] for c in service_db.calls_for("shops", "update") for f in c.filters if f[1] == "id"}
    assert updated == {SHOP_ID, SHOP2_ID}
    assert _final_update(service_db)["status"] == "completed"


def test_request_not_recorded_returns_503_and_deletes_nothing(client, service_db):
    service_db.errors[(TABLE, "upsert")] = RuntimeError("relation does not exist")
    r = _callback(client)
    assert r.status_code == 503
    assert "confirmation_code" not in r.text
    assert service_db.calls_for("bot_conversations", "delete") == []
    assert service_db.calls_for("shops", "update") == []


def test_invalid_signed_request_rejected(client, service_db):
    r = client.post("/facebook/data-deletion", data={"signed_request": _signed({"user_id": FB_USER}, "wrong")})
    assert r.status_code == 400
    assert service_db.calls == []


@pytest.mark.parametrize("stored", ["pending", "completed", "failed"])
def test_status_endpoint_returns_stored_status(client, service_db, stored):
    code = api_fb.make_deletion_code(FB_USER)
    service_db.responses[(TABLE, "select")] = [{"status": stored}]
    r = client.get("/facebook/data-deletion/status", params={"code": code})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True and body["status"] == stored and body["requested_at"]
    (q,) = service_db.calls_for(TABLE, "select")
    assert ("eq", "code", code) in q.filters


def test_status_endpoint_without_record_is_unknown_not_completed(client, service_db):
    code = api_fb.make_deletion_code(FB_USER)
    r = client.get("/facebook/data-deletion/status", params={"code": code})
    assert r.json()["valid"] is True and r.json()["status"] == "unknown"


def test_status_endpoint_db_error_is_503(client, service_db):
    code = api_fb.make_deletion_code(FB_USER)
    service_db.errors[(TABLE, "select")] = RuntimeError("db down")
    r = client.get("/facebook/data-deletion/status", params={"code": code})
    assert r.status_code == 503


def test_status_endpoint_forged_code_skips_db(client, service_db):
    r = client.get("/facebook/data-deletion/status", params={"code": "abc.def"})
    assert r.json() == {"valid": False, "status": "unknown"}
    assert service_db.calls == []


def _code(sql: str) -> str:
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def test_migration_0029_backend_only_status_table():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "create table if not exists public.data_deletion_requests" in code
    assert "check (status in ('pending', 'completed', 'failed'))" in code
    assert "alter table public.data_deletion_requests enable row level security;" in code
    assert "revoke all on table public.data_deletion_requests from public, anon, authenticated;" in code
    assert "grant select, insert, update on table public.data_deletion_requests to service_role;" in code
    assert "create policy" not in code and "drop table" not in code and "security definer" not in code
    assert code.count("begin;") == 1 and code.count("commit;") == 1
