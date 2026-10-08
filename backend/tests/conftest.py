"""Test harness: in-process TestClient with fake Supabase clients (no network).

Two separate fakes are wired in:
  - `user_db`    — the per-request JWT client (CurrentAuth.client, RLS applies)
  - `service_db` — what `get_service_client()` returns (service_role, no RLS)
so a test can tell which client performed each write.
"""
import os

# No real Supabase: blank credentials override any local .env before the app loads.
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_ANON_KEY"] = ""
# default is now production (fail-closed); tests run in development explicitly.
os.environ["APP_ENV"] = "development"

import pytest
from fastapi.testclient import TestClient

import app.api.facebook
import app.api.orders
import app.api.products
import app.api.shops
from app.core.security import CurrentAuth, get_current_auth
from app.main import app as fastapi_app

USER_ID = "11111111-1111-1111-1111-111111111111"


class FakeResult:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class FakeQuery:
    """One recorded call chain: table → operation(payload) → filters → execute()."""

    def __init__(self, db, table):
        self._db = db
        self.table = table
        self.op = None
        self.payload = None
        self.filters = []

    def select(self, *columns, **kwargs):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def upsert(self, payload):
        self.op, self.payload = "upsert", payload
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, list(values)))
        return self

    def gte(self, column, value):
        self.filters.append(("gte", column, value))
        return self

    def lt(self, column, value):
        self.filters.append(("lt", column, value))
        return self

    def or_(self, expr):
        self.filters.append(("or", expr, None))
        return self

    def limit(self, n):
        return self

    def order(self, *args, **kwargs):
        return self

    def execute(self):
        self._db.calls.append(self)
        if (self.table, self.op) in self._db.errors:
            raise self._db.errors[(self.table, self.op)]
        return FakeResult(
            self._db.responses.get((self.table, self.op), []),
            count=self._db.counts.get((self.table, self.op)),
        )


class FakeRpc:
    def __init__(self, db, fn, params):
        self._db, self.fn, self.params = db, fn, params

    def execute(self):
        self._db.rpc_calls.append(self)
        if self.fn in self._db.rpc_errors:
            raise self._db.rpc_errors[self.fn]
        return FakeResult(self._db.rpc_responses.get(self.fn))


class FakeSupabase:
    """Records every executed query; `.data` is configurable per (table, operation)."""

    def __init__(self):
        self.calls: list[FakeQuery] = []
        self.responses: dict[tuple[str, str], list] = {}
        self.counts: dict[tuple[str, str], int] = {}
        self.rpc_calls: list[FakeRpc] = []
        self.rpc_errors: dict[str, Exception] = {}  # fn name → exception raised on execute()
        self.rpc_responses: dict[str, object] = {}  # fn name → `.data` returned by execute()
        self.errors: dict[tuple[str, str], Exception] = {}  # (table, op) → exception on execute()

    def table(self, name):
        return FakeQuery(self, name)

    def rpc(self, fn, params):
        return FakeRpc(self, fn, params)

    def calls_for(self, table, op):
        return [c for c in self.calls if c.table == table and c.op == op]


@pytest.fixture
def user_db():
    return FakeSupabase()


@pytest.fixture
def service_db(monkeypatch):
    db = FakeSupabase()
    for module in (app.api.products, app.api.shops, app.api.facebook, app.api.orders):
        monkeypatch.setattr(module, "get_service_client", lambda: db)
    return db


@pytest.fixture
def client(user_db, service_db):
    fastapi_app.dependency_overrides[get_current_auth] = lambda: CurrentAuth(
        user_id=USER_ID, email="seller@test.local", client=user_db
    )
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """In-memory per-IP buckets are process-global; keep tests independent."""
    from app.core import ratelimit

    from app.api import webhook

    ratelimit._HITS.clear()
    webhook._RATE_HITS.clear()
    yield
    ratelimit._HITS.clear()
    webhook._RATE_HITS.clear()
