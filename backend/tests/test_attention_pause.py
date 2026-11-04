"""S20-4 (A-035): panel API for paused conversations.

* GET  /shops/{id}/attention          -> needs_attention OR paused (bot_paused_until >= now); 0033-less fallback
* POST /shops/{id}/attention/{psid}/resolve -> clears needs_attention AND the pause; 0033-less fallback
* POST /shops/{id}/attention/{psid}/resume  -> clears only the pause; ownership via the user client

Fake Supabase only (tests/conftest.py); nothing leaves the process.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

import pytest

import app.api.shops as shops_api
from tests.conftest import FakeQuery, FakeSupabase

SHOP_ID = "22222222-2222-2222-2222-222222222222"
PSID = "7654321098765432"
PAUSE_WARNING = "bot_conversations.bot_paused_until missing"
URL = f"/shops/{SHOP_ID}/attention"


class _PauseQuery(FakeQuery):
    """Remembers selected columns; behaves like a DB without migration 0033 when asked to."""

    columns = ""

    def select(self, *columns, **kwargs):
        self.columns = columns[0] if columns else ""
        return super().select(*columns, **kwargs)

    def execute(self):
        db = self._db
        touches_pause = (
            (self.op == "select" and "bot_paused_until" in self.columns)
            or (self.op == "select" and any(f[0] == "or" and "bot_paused_until" in f[1] for f in self.filters))
            or (self.op == "update" and "bot_paused_until" in (self.payload or {}))
        )
        if db.pause_missing and touches_pause:
            db.calls.append(self)
            raise RuntimeError("column bot_conversations.bot_paused_until does not exist")
        return super().execute()


class PauseDB(FakeSupabase):
    def __init__(self, pause_missing=False):
        super().__init__()
        self.pause_missing = pause_missing

    def table(self, name):
        return _PauseQuery(self, name)


@pytest.fixture
def user_db():
    return PauseDB()


@pytest.fixture(autouse=True)
def _reset_flag(monkeypatch):
    monkeypatch.setattr(shops_api, "_PAUSE_COLUMN_WARNED", False, raising=False)


def _iso(delta_hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=delta_hours)).isoformat()


def _row(psid=PSID, *, needs=False, paused=None, attention_at=None, updated_at="2026-11-05T09:00:00+00:00",
         messages=None):
    return {
        "psid": psid,
        "messages": messages if messages is not None else [{"role": "user", "content": " გამარჯობა "}],
        "attention_at": attention_at,
        "updated_at": updated_at,
        "needs_attention": needs,
        "bot_paused_until": paused,
    }


def _owner(user_db):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID}]


def _updates(db):
    return db.calls_for("bot_conversations", "update")


# ---------------------------------------------------------------- GET /attention

def test_list_returns_paused_only_conversation(client, user_db):
    future = _iso(3)
    user_db.responses[("bot_conversations", "select")] = [_row(paused=future)]

    r = client.get(URL)

    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1 and body["attention_count"] == 0
    item = body["items"][0]
    assert item["needs_attention"] is False
    assert datetime.fromisoformat(item["paused_until"]) == datetime.fromisoformat(future)
    assert item["last_message"] == "გამარჯობა"
    assert item["at"] == "2026-11-05T09:00:00+00:00"  # paused-only: updated_at, not a stale attention_at


def test_list_query_selects_pause_and_filters_with_or(client, user_db):
    user_db.responses[("bot_conversations", "select")] = []

    assert client.get(URL).status_code == 200

    q = user_db.calls_for("bot_conversations", "select")[0]
    assert "bot_paused_until" in q.columns and "needs_attention" in q.columns
    assert ("eq", "shop_id", SHOP_ID) in q.filters
    ors = [f[1] for f in q.filters if f[0] == "or"]
    assert len(ors) == 1
    assert "needs_attention.eq.true" in ors[0] and "bot_paused_until.gte." in ors[0]
    # `+` would be read as a space in the URL; timestamp must be the Z form
    assert "+" not in ors[0]
    assert re.search(r"bot_paused_until\.gte\.\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", ors[0])
    # the old query's hard filter is gone (it would hide paused-only rows)
    assert ("eq", "needs_attention", True) not in q.filters


def test_list_attention_count_counts_only_needs_attention(client, user_db):
    user_db.responses[("bot_conversations", "select")] = [
        _row("1", needs=True, attention_at="2026-11-05T10:00:00+00:00"),
        _row("2", needs=True, paused=_iso(2), attention_at="2026-11-05T08:00:00+00:00"),
        _row("3", needs=False, paused=_iso(5)),
    ]

    body = client.get(URL).json()

    assert body["count"] == 3
    assert body["attention_count"] == 2
    by_psid = {i["psid"]: i for i in body["items"]}
    assert by_psid["1"]["needs_attention"] is True and by_psid["1"]["paused_until"] is None
    assert by_psid["1"]["at"] == "2026-11-05T10:00:00+00:00"  # attention_at wins for handoffs
    assert by_psid["2"]["needs_attention"] is True and by_psid["2"]["paused_until"] is not None
    assert by_psid["3"]["needs_attention"] is False


@pytest.mark.parametrize(
    "raw",
    [_iso(-3), "not-a-date", "", None, "2020-01-01T00:00:00Z"],
    ids=["past", "garbage", "empty", "none", "past-z"],
)
def test_list_past_or_bad_pause_is_null(client, user_db, raw):
    user_db.responses[("bot_conversations", "select")] = [_row(needs=True, paused=raw)]

    item = client.get(URL).json()["items"][0]

    assert item["paused_until"] is None
    assert item["needs_attention"] is True


def test_list_pause_without_timezone_treated_as_utc(client, user_db):
    naive = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(tzinfo=None).isoformat()
    user_db.responses[("bot_conversations", "select")] = [_row(paused=naive)]

    item = client.get(URL).json()["items"][0]

    assert item["paused_until"] is not None
    assert item["paused_until"].endswith("+00:00")


def test_list_without_migration_0033_uses_old_query(client, user_db, caplog):
    user_db.pause_missing = True
    user_db.responses[("bot_conversations", "select")] = [
        {"psid": PSID, "messages": [{"role": "user", "content": "ფასი?"}],
         "attention_at": "2026-11-05T10:00:00+00:00", "updated_at": "2026-11-05T10:01:00+00:00"},
    ]

    with caplog.at_level(logging.WARNING, logger="app"):
        r = client.get(URL)
        client.get(URL)  # second request: the WARNING must not repeat

    assert r.status_code == 200
    assert r.json() == {
        "items": [{
            "psid": PSID, "last_message": "ფასი?", "at": "2026-11-05T10:00:00+00:00",
            "needs_attention": True, "paused_until": None,
        }],
        "count": 1,
        "attention_count": 1,
    }
    old = user_db.calls_for("bot_conversations", "select")[1]  # [0] is the failed new query
    assert ("eq", "needs_attention", True) in old.filters
    assert "bot_paused_until" not in old.columns
    assert sum(PAUSE_WARNING in m for m in caplog.messages) == 1
    assert PSID not in caplog.text


def test_list_both_queries_fail_returns_empty(client, user_db):
    user_db.errors[("bot_conversations", "select")] = RuntimeError("relation does not exist")

    r = client.get(URL)

    assert r.status_code == 200
    assert r.json() == {"items": [], "count": 0, "attention_count": 0}


def test_list_uses_last_user_message(client, user_db):
    user_db.responses[("bot_conversations", "select")] = [_row(needs=True, messages=[
        {"role": "user", "content": "პირველი"},
        {"role": "operator", "content": "ოპერატორის პასუხი"},
        {"role": "assistant", "content": "ბოტი"},
    ])]

    assert client.get(URL).json()["items"][0]["last_message"] == "პირველი"


# ---------------------------------------------------------------- POST /resolve

def test_resolve_clears_flag_and_pause_in_one_service_update(client, user_db, service_db):
    _owner(user_db)

    r = client.post(f"{URL}/{PSID}/resolve")

    assert r.status_code == 200 and r.json() == {"ok": True}
    ups = _updates(service_db)
    assert len(ups) == 1
    assert ups[0].payload == {"needs_attention": False, "bot_paused_until": None}
    assert ("eq", "shop_id", SHOP_ID) in ups[0].filters
    assert ("eq", "psid", PSID) in ups[0].filters
    assert _updates(user_db) == []  # the write goes through the service client only


def test_resolve_without_migration_0033_retries_with_flag_only(client, user_db, monkeypatch, caplog):
    _owner(user_db)
    db = PauseDB(pause_missing=True)
    monkeypatch.setattr(shops_api, "get_service_client", lambda: db)

    with caplog.at_level(logging.WARNING, logger="app"):
        r = client.post(f"{URL}/{PSID}/resolve")

    assert r.status_code == 200 and r.json() == {"ok": True}
    payloads = [u.payload for u in _updates(db)]
    assert payloads == [{"needs_attention": False, "bot_paused_until": None}, {"needs_attention": False}]
    second = _updates(db)[1]
    assert ("eq", "shop_id", SHOP_ID) in second.filters and ("eq", "psid", PSID) in second.filters
    assert sum(PAUSE_WARNING in m for m in caplog.messages) == 1


def test_resolve_both_updates_failing_is_silent(client, user_db, service_db):
    _owner(user_db)
    service_db.errors[("bot_conversations", "update")] = RuntimeError("db down")

    r = client.post(f"{URL}/{PSID}/resolve")

    assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(_updates(service_db)) == 2


def test_resolve_foreign_shop_is_404_and_writes_nothing(client, user_db, service_db):
    user_db.responses[("shops", "select")] = []

    r = client.post(f"{URL}/{PSID}/resolve")

    assert r.status_code == 404
    assert _updates(service_db) == []


# ---------------------------------------------------------------- POST /resume

def test_resume_clears_only_the_pause(client, user_db, service_db):
    _owner(user_db)

    r = client.post(f"{URL}/{PSID}/resume")

    assert r.status_code == 200
    assert r.json() == {"ok": True, "paused_until": None}
    ups = _updates(service_db)
    assert len(ups) == 1
    assert ups[0].payload == {"bot_paused_until": None}  # needs_attention untouched
    assert ("eq", "shop_id", SHOP_ID) in ups[0].filters
    assert ("eq", "psid", PSID) in ups[0].filters
    owner_check = user_db.calls_for("shops", "select")
    assert owner_check and ("eq", "id", SHOP_ID) in owner_check[0].filters


def test_resume_foreign_shop_is_404_and_writes_nothing(client, user_db, service_db):
    user_db.responses[("shops", "select")] = []  # RLS hides somebody else's shop

    r = client.post(f"{URL}/{PSID}/resume")

    assert r.status_code == 404
    assert r.json()["detail"] == "მაღაზია ვერ მოიძებნა ან არ არის თქვენი"
    assert _updates(service_db) == []


def test_resume_db_error_is_503_and_logs_without_psid(client, user_db, service_db, caplog):
    _owner(user_db)
    service_db.errors[("bot_conversations", "update")] = RuntimeError(f"boom for {PSID}")

    with caplog.at_level(logging.WARNING, logger="app"):
        r = client.post(f"{URL}/{PSID}/resume")

    assert r.status_code == 503
    assert r.json() == {"detail": "ბოტის ჩართვა ახლა ვერ მოხერხდა — სცადეთ მოგვიანებით."}
    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert warnings
    assert SHOP_ID in caplog.text and "RuntimeError" in caplog.text
    assert PSID not in caplog.text


def test_resume_without_migration_0033_is_503(client, user_db, monkeypatch):
    _owner(user_db)
    monkeypatch.setattr(shops_api, "get_service_client", lambda: PauseDB(pause_missing=True))

    r = client.post(f"{URL}/{PSID}/resume")

    assert r.status_code == 503
