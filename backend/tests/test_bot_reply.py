"""S14-5 / S16-8: the webhook fallback and /test-chat through the real graph (`run_turn`) with fake SDK clients
(no network, no real key).

The get_bot_reply-level checks (byte-identical cached layers, usage rows, key-less bot, reference photos)
live in tests/test_graph.py since S16-6; the old get_bot_reply was removed in S16-8.
"""
import logging
import time
import uuid
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

import app.api.chat as chat
import app.api.webhook as webhook
from app.config import get_settings
from app.services import graph, llm
from tests.conftest import FakeSupabase
from tests.test_reply_delivery import PSID, _run, env  # noqa: F401  (env is a fixture)
from tests.test_reply_delivery import SHOP_ID as WEBHOOK_SHOP_ID

SHOP_ID = str(uuid.uuid4())
SHOP = {"id": SHOP_ID, "name": "Tbilisi Style", "description": "Clothes", "currency": "GEL",
        "knowledge": "Delivery in Tbilisi: 5 GEL."}
REQ = httpx2.Request("POST", "https://api.example.invalid/v1/x")


def _products(n):
    return [
        {"id": f"{i:04d}", "name": f"Item {i}", "price": 10 + i, "quantity": 1 + i % 3,
         "sku": f"S{i}", "description": f"desc {i}"}
        for i in range(n)
    ]


def _claude_response(text="  Hello!  "):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=11, output_tokens=6, cache_read_input_tokens=4,
                              cache_creation_input_tokens=2),
    )


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Harness:
    """Fake Claude SDK client + fake clock + fake usage DB, wired into the real modules."""

    def __init__(self, monkeypatch, **settings_update):
        self.requests = []
        self.factory_calls = 0
        self.result = None  # response object or exception returned/raised by create()
        self.duration = 0.0  # simulated seconds each create() takes
        self.clock = FakeClock()
        self.usage_db = FakeSupabase()
        self.monkeypatch = monkeypatch
        monkeypatch.setattr(llm, "time", SimpleNamespace(
            monotonic=self.clock.monotonic, sleep=self.clock.sleep))
        # graph.run_turn computes the absolute turn deadline that llm checks: both must read the SAME
        # clock. With only llm faked, the deadline came from the real monotonic (machine uptime) —
        # fine on a long-running dev box, "turn budget exhausted" on a freshly booted CI runner.
        monkeypatch.setattr(graph, "time", SimpleNamespace(monotonic=self.clock.monotonic))
        monkeypatch.setattr(llm, "get_service_client", lambda: self.usage_db)
        self.set_settings(**settings_update)

        def create(**kwargs):
            self.requests.append(kwargs)
            self.clock.now += self.duration
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

        def factory(s):
            self.factory_calls += 1
            return SimpleNamespace(messages=SimpleNamespace(create=create),
                                   responses=SimpleNamespace(create=create))

        monkeypatch.setattr(llm, "_anthropic_client", factory)
        monkeypatch.setattr(llm, "_openai_client", factory)

    def set_settings(self, **update):
        s = get_settings().model_copy(update=update)
        for module in (llm, chat):
            self.monkeypatch.setattr(module, "get_settings", lambda: s)
        self.settings = s
        return s


@pytest.fixture
def h(monkeypatch):
    harness = Harness(monkeypatch)
    harness.result = _claude_response()
    return harness


# ---------------------------------------------------------------------------
# (1) webhook fallback when the LLM times out
# ---------------------------------------------------------------------------
def test_webhook_sends_fallback_when_llm_times_out(env, h, monkeypatch, caplog):  # noqa: F811
    db, sent, _ = env
    h.result = anthropic.APITimeoutError(REQ)
    h.duration = h.settings.llm_timeout_seconds  # every attempt hangs until its timeout fires
    monkeypatch.setattr(webhook, "run_turn", graph.run_turn)  # env stubbed it

    with caplog.at_level(logging.ERROR, logger="app"):
        _run(text="წითელი მაისური რა ღირს?")  # not a template: it must reach the model

    assert sent == ["ბოდიში, ამ წუთას ვერ გიპასუხებთ. სცადეთ ცოტა ხანში."]
    assert any(WEBHOOK_SHOP_ID in r.getMessage() for r in caplog.records)
    assert PSID not in "".join(r.getMessage() for r in caplog.records)
    # one own retry only, and the whole call stays inside the total budget
    assert len(h.requests) == 2
    assert h.clock.now - 1000.0 <= llm.LLM_TOTAL_BUDGET_SECONDS
    assert h.usage_db.calls_for("llm_usage", "insert") == []


# ---------------------------------------------------------------------------
# (2) /test-chat
# ---------------------------------------------------------------------------
def _chat_payload():
    # not a greeting: "hello" is a template now and would never reach the (fake) model
    return {"shop_id": SHOP_ID, "message": "what is the price of Item 1?", "history": []}


@pytest.fixture
def chat_db(service_db, monkeypatch):
    service_db.responses[("shops", "select")] = [SHOP]
    service_db.responses[("products", "select")] = _products(3)
    monkeypatch.setattr(chat, "get_service_client", lambda: service_db)
    return service_db


def test_test_chat_503_names_the_provider_key_when_not_ready(client, chat_db, h):
    h.set_settings(anthropic_api_key="")
    r = client.post("/test-chat", json=_chat_payload())
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]
    assert h.factory_calls == 0


def test_test_chat_503_names_openai_key_for_openai(client, chat_db, h):
    h.set_settings(llm_provider="openai", openai_api_key="")
    r = client.post("/test-chat", json=_chat_payload())
    assert r.status_code == 503
    assert "OPENAI_API_KEY" in r.json()["detail"]


def test_test_chat_ok_with_fake_client(client, chat_db, h):
    r = client.post("/test-chat", json=_chat_payload())
    assert r.status_code == 200, r.text
    assert r.json() == {"reply": "Hello!", "products_in_context": 3, "model": "claude-haiku-5-5"}
    assert len(h.requests) == 1


def test_test_chat_greeting_is_a_template_without_an_llm_call(client, chat_db, h):
    payload = {"shop_id": SHOP_ID, "message": "გამარჯობა", "history": []}
    r = client.post("/test-chat", json=payload)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "reply": "გამარჯობა! 😊 რით შემიძლია დაგეხმაროთ?",
        "products_in_context": 3, "model": "claude-haiku-5-5",
    }
    assert h.requests == [] and h.factory_calls == 0
    assert h.usage_db.calls_for("llm_usage", "insert") == []


def test_test_chat_greeting_still_503_without_a_key(client, chat_db, h):
    h.set_settings(anthropic_api_key="")
    r = client.post("/test-chat", json={"shop_id": SHOP_ID, "message": "გამარჯობა", "history": []})
    assert r.status_code == 503
    assert h.factory_calls == 0


def test_test_chat_is_404_in_production(client, chat_db, h):
    h.set_settings(app_env="production")
    r = client.post("/test-chat", json=_chat_payload())
    assert r.status_code == 404
    assert h.factory_calls == 0


def test_test_chat_llm_failure_is_502(client, chat_db, h):
    h.result = ValueError("bad request")
    r = client.post("/test-chat", json=_chat_payload())
    assert r.status_code == 502


# ---------------------------------------------------------------------------
# (3) regression: the harness must not depend on the machine's uptime
# ---------------------------------------------------------------------------
@pytest.fixture
def fresh_vm_uptime(monkeypatch):
    """Real time.monotonic() as on a freshly booted CI runner (~50 s), still advancing normally.

    A dev box with days of uptime returns a huge monotonic value, which hid a harness that faked
    the clock only in llm while graph took the turn deadline from the real clock."""
    real = time.monotonic
    base = real()
    monkeypatch.setattr(time, "monotonic", lambda: real() - base + 50.0)


def test_webhook_timeout_fallback_on_a_freshly_booted_machine(fresh_vm_uptime, env, h, monkeypatch):  # noqa: F811
    _, sent, _ = env
    h.result = anthropic.APITimeoutError(REQ)
    h.duration = h.settings.llm_timeout_seconds
    monkeypatch.setattr(webhook, "run_turn", graph.run_turn)

    _run(text="წითელი მაისური რა ღირს?")

    assert len(h.requests) == 2  # the model was really called (and retried once)
    assert sent == ["ბოდიში, ამ წუთას ვერ გიპასუხებთ. სცადეთ ცოტა ხანში."]


def test_test_chat_ok_on_a_freshly_booted_machine(fresh_vm_uptime, client, chat_db, h):
    r = client.post("/test-chat", json=_chat_payload())
    assert r.status_code == 200, r.text
    assert len(h.requests) == 1
