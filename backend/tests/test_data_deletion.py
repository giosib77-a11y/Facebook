"""A-017: Meta Data Deletion callback records a real status; errors are not swallowed."""
import base64
import hashlib
import hmac
import json
import re
from pathlib import Path

import pytest

import app.api.facebook as api_fb
from app.config import Settings

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
    # the actual erasure happened: shop conversations, shop page data, customer conversations
    deletes = service_db.calls_for("bot_conversations", "delete")
    assert ("eq", "shop_id", SHOP_ID) in deletes[0].filters
    assert ("eq", "psid", FB_USER) in deletes[1].filters
    assert service_db.calls_for("shops", "update")[0].payload["facebook_page_token"] is None


@pytest.mark.parametrize("table,op", [
    ("bot_conversations", "delete"),
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


def test_customer_counter_row_is_deleted_by_psid(client, service_db):
    # A-030: bot_customers (per-customer monthly counter, keyed by psid) is erased too
    r = _callback(client)
    assert r.status_code == 200
    (d,) = service_db.calls_for("bot_customers", "delete")
    assert ("eq", "psid", FB_USER) in d.filters
    assert _final_update(service_db)["status"] == "completed"


def test_bot_customers_delete_error_is_recorded_as_failed(client, service_db):
    service_db.errors[("bot_customers", "delete")] = RuntimeError("db down")
    r = _callback(client)
    assert r.status_code == 200 and r.json()["confirmation_code"]
    final = _final_update(service_db)
    assert final["status"] == "failed" and final["error"] == "RuntimeError"
    assert "fb_user_id" not in final  # kept for a manual retry


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
