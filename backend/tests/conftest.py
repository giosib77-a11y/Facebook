"""Test harness: in-process TestClient with fake Supabase clients (no network).

Two separate fakes are wired in:
  - `user_db`    — the per-request JWT client (CurrentAuth.client, RLS applies)
  - `service_db` — what `get_service_client()` returns (secret key, no RLS)
so a test can tell which client performed each write.
"""
# ruff: noqa: E402  (env must be pinned before the app imports below)
import os

# Tests never read a local .env (T19): the env_file is switched off on the Settings class
# before any Settings() is built, and every string setting is pinned to a blank value so a
# stray shell variable cannot leak in either. Must stay above the app imports.
from app.config import Settings

Settings.model_config["env_file"] = None
for _name in (
    "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY",
    "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "ORIGIN_SECRET",
    "OPENAI_API_KEY", "FB_APP_ID", "FB_APP_SECRET", "FB_VERIFY_TOKEN", "FB_REDIRECT_URI",
    "FB_LOGIN_CONFIG_ID", "FB_TOKEN_ENCRYPTION_KEY", "PUBLIC_BASE_URL", "ADMIN_USER_IDS",
    "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "NOTIFY_EMAIL_FROM",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
):
    os.environ[_name] = ""
# LLM: default test setup = configured bot (claude + dummy key). A test of a disabled bot
# must override settings explicitly.
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key-not-real"
os.environ["LLM_PROVIDER"] = "claude"
# non-string settings / defaults: an empty string would override the default (or fail to parse)
for _name in (
    "CLAUDE_MODEL", "OPENAI_MODEL", "LLM_TIMEOUT_SECONDS",
    "SMTP_PORT", "LLM_KILL_SWITCH",
    # Stage 21: worker / CSP / USD ბიუჯეტი / ფასები — ტესტებში მხოლოდ კოდის default-ები
    "BOT_MAX_CONCURRENCY", "WEBHOOK_POLL_SECONDS", "WEBHOOK_MAX_ATTEMPTS",
    "WEBHOOK_CLAIM_STALE_SECONDS", "CSP_REPORT_ONLY", "LLM_DAILY_USD_CAP",
    "LLM_DAILY_USD_SHOP_DIVISOR", "LLM_MONTHLY_USD_FREE", "LLM_MONTHLY_USD_BASIC",
    "LLM_MONTHLY_USD_STANDARD", "LLM_MONTHLY_USD_BUSINESS", "LLM_PRICES",
):
    os.environ.pop(_name, None)
# Stage 21: webhook_inbox worker ტესტებში გამორთულია (APP_ENV ქვემოთ development-ია, მაგრამ ცხადად)
os.environ["WEBHOOK_INBOX_ENABLED"] = "false"
# Stage 16: LangGraph/LangSmith tracing would send conversations to a third party. Never in tests.
for _name in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY"):
    os.environ.pop(_name, None)
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
        self.kwargs = {}  # insert/upsert-ის დამატებითი არგუმენტები (on_conflict, ignore_duplicates, ...)

    def select(self, *columns, **kwargs):
        self.op = "select"
        return self

    def insert(self, payload, **kwargs):
        self.op, self.payload, self.kwargs = "insert", payload, kwargs
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def upsert(self, payload, **kwargs):
        self.op, self.payload, self.kwargs = "upsert", payload, kwargs
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def neq(self, column, value):
        self.filters.append(("neq", column, value))
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
def _app_logger_propagates(monkeypatch):
    """app.main sets propagate=False on the `app` logger (T22); caplog hooks the root logger,
    so tests need propagation back on. The stdout-handler test inspects handlers directly."""
    import logging

    monkeypatch.setattr(logging.getLogger("app"), "propagate", True)


@pytest.fixture(autouse=True)
def _block_real_llm_clients(monkeypatch):
    """No test may build a real Anthropic/OpenAI client (network + real key). A test that needs
    the real factory (with a fake SDK class) restores it from tests.test_llm_client."""
    import app.services.llm

    def _blocked(*args, **kwargs):
        raise RuntimeError("real LLM client blocked in tests")

    monkeypatch.setattr(app.services.llm, "_anthropic_client", _blocked)
    monkeypatch.setattr(app.services.llm, "_openai_client", _blocked)


@pytest.fixture(autouse=True)
def _block_real_notify(monkeypatch):
    """No test may reach a real SMTP server or Telegram (Stage 20, services/notify.py). A test
    that needs a send installs its own notify._TRANSPORT / notify._smtp_connect."""
    import httpx

    from app.services import notify

    blocked: list = []

    def _http(request):
        blocked.append(request)
        return httpx.Response(599)

    def _smtp(*args, **kwargs):
        blocked.append(args)
        raise OSError("blocked in tests")

    monkeypatch.setattr(notify, "_TRANSPORT", httpx.MockTransport(_http))
    monkeypatch.setattr(notify, "_smtp_connect", _smtp)
    notify._THROTTLE.clear()
    yield
    notify._THROTTLE.clear()
    assert not blocked, "real notify HTTP/SMTP attempted"


@pytest.fixture(autouse=True)
def _reset_llm_budget():
    """services/budget.py keeps a process-global cache and flags; keep tests independent."""
    from app.services import budget

    budget.reset()
    yield
    budget.reset()


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
