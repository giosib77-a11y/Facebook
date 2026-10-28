"""S14-5: real get_bot_reply -> prompt -> llm with fake SDK clients (no network, no real key).

Covers: byte-identical cached layers across messages (owner test), usage recording, key-less
bot, webhook fallback on an LLM timeout, /test-chat, and reference photos coming from the same
relevant subset the prompt uses.
"""
import json
import logging
import uuid
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

import app.api.chat as chat
import app.api.webhook as webhook
import app.services.facebook as facebook
from app.services import bot, graph, llm
from app.services.prompt import _sort_key
from tests.conftest import FakeSupabase
from tests.test_reply_delivery import PSID, _run, env  # noqa: F401  (env is a fixture)
from tests.test_reply_delivery import SHOP_ID as WEBHOOK_SHOP_ID

SHOP_ID = str(uuid.uuid4())
SHOP = {"id": SHOP_ID, "name": "Tbilisi Style", "description": "Clothes", "currency": "GEL",
        "knowledge": "Delivery in Tbilisi: 5 GEL."}
LAYER1_FIXTURE = (Path(__file__).parent / "fixtures" / "prompt_layer1.txt").read_text(
    encoding="utf-8").replace("\r\n", "\n")
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


def _openai_response(text="  Hello!  "):
    return SimpleNamespace(
        output_text=text,
        usage=SimpleNamespace(input_tokens=50, output_tokens=7,
                              input_tokens_details=SimpleNamespace(cached_tokens=20, cache_write_tokens=10)),
    )


def _stable_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()


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
    """Fake Claude/OpenAI SDK clients + fake clock + fake usage DB, wired into the real modules."""

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
        s = bot.get_settings().model_copy(update=update)
        for module in (bot, llm, chat):
            self.monkeypatch.setattr(module, "get_settings", lambda: s)
        self.settings = s
        return s


@pytest.fixture
def h(monkeypatch):
    harness = Harness(monkeypatch)
    harness.result = _claude_response()
    return harness


@pytest.fixture
def h_openai(monkeypatch):
    harness = Harness(monkeypatch, llm_provider="openai", openai_api_key="test-openai-key-not-real")
    harness.result = _openai_response()
    return harness


# ---------------------------------------------------------------------------
# (1) owner test, end to end: cached layers are byte-identical across messages
# ---------------------------------------------------------------------------
HISTORY_A = [{"role": "user", "content": "hi"}, {"role": "bot", "content": "hello!"}]
HISTORY_B = [{"role": "user", "content": "Item 3 price?"}, {"role": "bot", "content": "13 GEL"}]


@pytest.mark.parametrize("n_products", [5, 40])
def test_claude_system_is_byte_identical_across_messages(h, n_products):
    products = _products(n_products)
    first = bot.get_bot_reply(SHOP, products, "Item 3", HISTORY_A)
    second = bot.get_bot_reply(SHOP, products, "Item 25 please, size M?", HISTORY_B)
    assert first == second == "Hello!"  # stripped

    a, b = (r["system"] for r in h.requests)
    assert _stable_bytes(a) == _stable_bytes(b)
    assert a[0]["text"] == LAYER1_FIXTURE
    assert a[0]["text"].encode("utf-8") == b[0]["text"].encode("utf-8")
    assert a[1]["text"].encode("utf-8") == b[1]["text"].encode("utf-8")
    # SF-1: L3 breakpoint is on the last history block, never on the variable final turn
    for r in h.requests:
        assert "cache_control" not in r
        assert r["messages"][-2]["content"][-1]["cache_control"] == {"type": "ephemeral"}
        assert all("cache_control" not in b for b in r["messages"][-1]["content"])
    # the per-message part really differs
    assert h.requests[0]["messages"][-1] != h.requests[1]["messages"][-1]
    if n_products > 30:
        # large catalogue: the relevant products travel in the final turn, not in the cached layers
        assert "Item 25" not in a[1]["text"]
        assert "Relevant products for this message" in h.requests[1]["messages"][-1]["content"][0]["text"]


@pytest.mark.parametrize("n_products", [5, 40])
def test_openai_developer_item_is_byte_identical_across_messages(h_openai, n_products):
    products = _products(n_products)
    bot.get_bot_reply(SHOP, products, "Item 3", HISTORY_A)
    bot.get_bot_reply(SHOP, products, "Item 25 please, size M?", HISTORY_B)

    a, b = (r["input"][0] for r in h_openai.requests)
    assert a["role"] == "developer"
    assert _stable_bytes(a) == _stable_bytes(b)
    assert a["content"][0]["text"] == LAYER1_FIXTURE
    assert h_openai.requests[0]["input"][-1] != h_openai.requests[1]["input"][-1]
    assert h_openai.requests[0]["model"] == h_openai.settings.openai_model


def test_system_is_independent_of_product_order(h):
    products = _products(40)
    bot.get_bot_reply(SHOP, products, "Item 3")
    bot.get_bot_reply(SHOP, list(reversed(products)), "Item 3")
    a, b = (r["system"] for r in h.requests)
    assert _stable_bytes(a) == _stable_bytes(b)


# ---------------------------------------------------------------------------
# (2) usage recording
# ---------------------------------------------------------------------------
def test_usage_recorded_with_shop_id(h):
    assert bot.get_bot_reply(SHOP, _products(3), "hi") == "Hello!"
    rows = h.usage_db.calls_for("llm_usage", "insert")
    assert len(rows) == 1
    assert rows[0].payload == {
        "shop_id": SHOP_ID, "provider": "claude", "model": h.settings.claude_model,
        "input_tokens": 11, "output_tokens": 6, "cache_read_tokens": 4, "cache_write_tokens": 2,
    }


def test_usage_recorded_for_openai(h_openai):
    bot.get_bot_reply(SHOP, _products(3), "hi")
    (row,) = h_openai.usage_db.calls_for("llm_usage", "insert")
    assert row.payload["provider"] == "openai"
    assert row.payload["shop_id"] == SHOP_ID
    assert (row.payload["input_tokens"], row.payload["cache_read_tokens"], row.payload["cache_write_tokens"]) == (
        20, 20, 10)


def test_reply_still_returned_when_usage_write_fails(h, caplog):
    h.usage_db.errors[("llm_usage", "insert")] = RuntimeError("db down")
    with caplog.at_level(logging.WARNING, logger="app"):
        assert bot.get_bot_reply(SHOP, _products(3), "hi") == "Hello!"
    assert any(SHOP_ID in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_no_usage_row_when_llm_call_fails(h):
    h.result = ValueError("bad request")
    with pytest.raises(ValueError):
        bot.get_bot_reply(SHOP, _products(3), "hi")
    assert h.usage_db.calls_for("llm_usage", "insert") == []


# ---------------------------------------------------------------------------
# (3) bot without a key
# ---------------------------------------------------------------------------
def test_not_ready_raises_runtime_error_without_building_a_client(h):
    h.set_settings(anthropic_api_key="")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        bot.get_bot_reply(SHOP, _products(3), "hi")
    assert h.factory_calls == 0 and h.requests == []
    assert h.usage_db.calls_for("llm_usage", "insert") == []


def test_not_ready_openai_names_openai_key(h):
    h.set_settings(llm_provider="openai", openai_api_key=" ")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        bot.get_bot_reply(SHOP, _products(3), "hi")
    assert h.factory_calls == 0


# ---------------------------------------------------------------------------
# (4) webhook fallback when the LLM times out# ---------------------------------------------------------------------------
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
# (5) /test-chat
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
# (6) reference photos come from the same relevant subset the prompt uses
# ---------------------------------------------------------------------------
@pytest.fixture
def downloads(monkeypatch):
    urls = []

    def fake_download(url, **kwargs):
        urls.append(url)
        return b"img-bytes", "image/jpeg"

    monkeypatch.setattr(facebook, "download_image", fake_download)
    monkeypatch.setattr(facebook, "is_own_storage_image_url", lambda url: True)
    return urls


def _photo_products(n):
    products = _products(n)
    for p in products:
        p["image_url"] = f"https://cdn.example.com/{p['id']}.jpg"
    return products


def _request_texts(request):
    return [b["text"] for b in request["messages"][-1]["content"] if b["type"] == "text"]


def test_reference_photos_follow_prompt_subset_regardless_of_db_order(h, downloads):
    products = _photo_products(40)
    customer = [(b"customer-photo", "image/jpeg")]

    bot.get_bot_reply(SHOP, products, "Item 33", images=customer)
    in_order = list(downloads)
    downloads.clear()
    bot.get_bot_reply(SHOP, list(reversed(products)), "Item 33", images=customer)
    reversed_order = list(downloads)

    assert in_order and set(in_order) == set(reversed_order)

    # every product whose reference photo was sent is listed as relevant in the same prompt
    for request in h.requests:
        texts = _request_texts(request)
        relevant_block = next(t for t in texts if t.startswith("Relevant products for this message"))
        labels = [t for t in texts if t.startswith("• ")]
        assert labels
        for label in labels:
            name = label.removeprefix("• ").split(" — ")[0]
            assert f"- {name} —" in relevant_block
        # the photo of the exact match is among them
        assert "• Item 33 —" in "".join(labels)
    assert "https://cdn.example.com/0033.jpg" in in_order


def test_reference_candidates_use_the_prompt_sort_order(h, downloads):
    products = list(reversed(_photo_products(40)))  # DB order is not guaranteed
    bot.get_bot_reply(SHOP, products, "something generic", images=[(b"c", "image/jpeg")])
    expected = [p["image_url"] for p in sorted(products, key=_sort_key)[:12]]
    assert sorted(downloads) == sorted(expected)  # downloads run in a thread pool: order is free


def test_no_reference_photos_downloaded_without_customer_photo(h, downloads):
    bot.get_bot_reply(SHOP, _photo_products(5), "Item 3")
    assert downloads == []
    assert all(b["type"] == "text" for b in h.requests[0]["messages"][-1]["content"])
