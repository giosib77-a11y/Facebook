"""S14-6 / S16-7: Georgian golden conversations, end to end, for both providers (offline).

Real chain: webhook._process_events -> graph.run_turn (preprocess -> agent <-> tools -> postprocess)
-> prompt -> llm, with fake Claude / OpenAI SDK clients (canned model output, tool calls included),
a fake service DB, and patched Facebook I/O. Checks what the customer receives, what the model
requests contain, and what the webhook stores.
"""
import base64
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.api.webhook as webhook
import app.services.bot as bot
import app.services.facebook as facebook
import app.services.llm as llm
from app.services import graph, tools
from tests.test_reply_delivery import PAGE_ID, PSID, SHOP_ID

GREETING_REPLY = "გამარჯობა! 😊 რით შემიძლია დაგეხმაროთ?"
HANDOFF_REPLY = "ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏"
CUSTOMER_PHOTO = b"customer-photo-bytes"
COMPLAINT = "ეს ნივთი გატეხილი მომივიდა და ძალიან უკმაყოფილო ვარ"

SHOP = {
    "id": SHOP_ID, "name": "ტესტ მაღაზია", "description": "ტანსაცმელი თბილისიდან",
    "currency": "GEL", "bot_language": "auto", "knowledge": "მიწოდება თბილისში: 5 ლარი.",
    "bot_enabled": True, "facebook_page_token": "enc", "subscription_tier": "free",
}
PRODUCTS = [
    {"id": "p1", "name": "წითელი მაისური", "price": 89, "quantity": 3, "sku": "RED-1",
     "description": "ზომები S-XL", "image_url": "https://storage.example.com/p1.jpg"},
    {"id": "p2", "name": "თეთრი პერანგი", "price": 65, "quantity": 0, "sku": "WHT-1",
     "description": "", "image_url": None},
    {"id": "p3", "name": "შავი ჯინსი", "price": 120, "quantity": 5, "sku": "BLK-1",
     "description": "", "image_url": "https://storage.example.com/p3.jpg"},
    {"id": "p4", "name": "ტყავის ქურთუკი", "price": 350, "quantity": 1, "sku": "JKT-1",
     "description": "", "image_url": None},
]


class Golden:
    """Wires fake provider clients and a fake DB into the real webhook -> graph -> prompt -> llm chain.

    Model output: `script` (one item per LLM request, in order; `str` = a text answer, or `g.calls(...)`)
    and then `default(n)` / `canned` once the script is used up."""

    def __init__(self, provider, monkeypatch, db):
        self.provider = provider
        self.db = db
        self.requests: list[dict] = []
        self.sent: list[str] = []
        self.canned = ""
        self.script: list = []
        self.default = None
        self.ref_downloads: list[str] = []

        update = {"llm_provider": provider}
        if provider == "openai":
            update["openai_api_key"] = "test-openai-key-not-real"
        s = webhook.get_settings().model_copy(update=update)
        for module in (webhook, bot, llm):
            monkeypatch.setattr(module, "get_settings", lambda: s)
        self.settings = s

        db.responses[("shops", "select")] = [SHOP]
        db.responses[("products", "select")] = PRODUCTS
        db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 1}]
        monkeypatch.setattr(webhook, "get_service_client", lambda: db)
        monkeypatch.setattr(llm, "get_service_client", lambda: db)
        monkeypatch.setattr(webhook, "decrypt", lambda token: "page-token")
        monkeypatch.setattr(webhook, "send_text_message", lambda tok, psid, text: self.sent.append(text))
        monkeypatch.setattr(webhook, "download_image", lambda url, timeout=8: (CUSTOMER_PHOTO, "image/jpeg"))

        def ref_download(url, **kwargs):
            self.ref_downloads.append(url)
            return b"ref:" + url.encode(), "image/jpeg"

        monkeypatch.setattr(facebook, "download_image", ref_download)
        monkeypatch.setattr(
            facebook, "is_own_storage_image_url", lambda url: url.startswith("https://storage.example.com/"))

        def claude_create(**kwargs):
            self.requests.append(kwargs)
            item = self._next_item()
            content = [SimpleNamespace(type="thinking", thinking="(model reasoning, never shown)")]
            if item["text"]:
                content.append(SimpleNamespace(type="text", text=item["text"]))
            content += [SimpleNamespace(type="tool_use", id=i, name=n, input=a) for i, n, a in item["calls"]]
            return SimpleNamespace(
                content=content, stop_reason="tool_use" if item["calls"] else "end_turn",
                usage=SimpleNamespace(input_tokens=120, output_tokens=18, cache_read_input_tokens=900,
                                      cache_creation_input_tokens=0),
            )

        def openai_create(**kwargs):
            self.requests.append(kwargs)
            item = self._next_item()
            output = [
                SimpleNamespace(type="function_call", call_id=i, name=n, arguments=json.dumps(a))
                for i, n, a in item["calls"]
            ]
            return SimpleNamespace(
                output_text=item["text"], output=output,
                usage=SimpleNamespace(input_tokens=1020, output_tokens=18,
                                      input_tokens_details=SimpleNamespace(cached_tokens=900, cache_write_tokens=0)),
            )

        monkeypatch.setattr(
            llm, "_anthropic_client", lambda s: SimpleNamespace(messages=SimpleNamespace(create=claude_create)))
        monkeypatch.setattr(
            llm, "_openai_client", lambda s: SimpleNamespace(responses=SimpleNamespace(create=openai_create)))

    # --- fake model output ----------------------------------------------------------------
    @staticmethod
    def calls(*calls, text=""):
        """A model answer with tool calls: calls = (id, tool name, arguments dict)."""
        return {"text": text, "calls": list(calls)}

    def _next_item(self):
        if self.script:
            item = self.script.pop(0)
        elif self.default is not None:
            item = self.default(len(self.requests))
        else:
            item = self.canned
        return {"text": item, "calls": []} if isinstance(item, str) else item

    # --- webhook side ---------------------------------------------------------------------
    def seed_history(self, turns):
        self.db.responses[("bot_conversations", "select")] = [{
            "messages": turns, "updated_at": datetime.now(timezone.utc).isoformat(),
        }]

    def run(self, message):
        """Process one customer message; returns the first model request (None for template replies)."""
        webhook._process_events({"object": "page", "entry": [{
            "id": PAGE_ID, "messaging": [{"sender": {"id": PSID}, "message": message}],
        }]})
        return self.requests[0] if self.requests else None

    # --- provider-neutral views of a request ---------------------------------------------
    def layer2(self, request):
        if self.provider == "claude":
            return request["system"][1]["text"]
        return request["input"][0]["content"][1]["text"]

    def history_turns(self, request):
        """Everything before the final user turn, as (role, text). First request of a turn only."""
        turns = request["messages"] if self.provider == "claude" else request["input"][1:]
        if self.provider == "claude":  # history turns are block lists on Claude (cache breakpoint)
            return [(t["role"], "".join(b["text"] for b in t["content"])) for t in turns[:-1]]
        return [(t["role"], t["content"]) for t in turns[:-1]]

    def final_blocks(self, request):
        turns = request["messages"] if self.provider == "claude" else request["input"]
        last = turns[-1]
        assert last["role"] == "user"
        return last["content"]

    def final_texts(self, request):
        kind = "text" if self.provider == "claude" else "input_text"
        return [b["text"] for b in self.final_blocks(request) if b["type"] == kind]

    def final_images(self, request):
        """Base64 payloads of the images in the final turn, in order."""
        out = []
        for b in self.final_blocks(request):
            if self.provider == "claude" and b["type"] == "image":
                assert b["source"]["type"] == "base64" and b["source"]["media_type"] == "image/jpeg"
                out.append(b["source"]["data"])
            elif self.provider == "openai" and b["type"] == "input_image":
                prefix = "data:image/jpeg;base64,"
                assert b["image_url"].startswith(prefix)
                out.append(b["image_url"][len(prefix):])
        return out

    def tool_names(self, request):
        return [t["name"] for t in request["tools"]]

    def tool_outputs(self, request):
        """Tool results the request carries: [{"id", "content"}]."""
        out = []
        if self.provider == "claude":
            for m in request["messages"]:
                if m["role"] == "user" and isinstance(m["content"], list):
                    out += [{"id": b["tool_use_id"], "content": b["content"]}
                            for b in m["content"] if b.get("type") == "tool_result"]
        else:
            out += [{"id": i["call_id"], "content": i["output"]}
                    for i in request["input"] if i.get("type") == "function_call_output"]
        return out

    def usage_rows(self):
        return [c.payload for c in self.db.calls_for("llm_usage", "insert")]

    def saved(self):
        (save,) = self.db.calls_for("bot_conversations", "upsert")
        return save.payload


@pytest.fixture(params=["claude", "openai"])
def g(request, monkeypatch, service_db):
    return Golden(request.param, monkeypatch, service_db)


def _assert_usage_recorded(g, n=1):
    """One llm_usage row per LLM request (the template route writes none)."""
    rows = g.usage_rows()
    assert len(rows) == n == len(g.requests)
    for row in rows:
        assert row["shop_id"] == SHOP_ID
        assert row["provider"] == g.provider
        assert row["model"] == g.settings.llm_model
        assert row["output_tokens"] == 18
        assert row["cache_read_tokens"] == 900


# --- (1) preprocess: templates never reach the model ------------------------------------------
def test_greeting_is_a_template_without_an_llm_request(g):
    g.canned = "must never be requested"

    request = g.run({"text": "გამარჯობა"})

    assert request is None and g.requests == []
    assert g.sent == [GREETING_REPLY]  # delivered unchanged
    assert g.saved()["messages"] == [
        {"role": "user", "content": "გამარჯობა"}, {"role": "bot", "content": GREETING_REPLY},
    ]
    assert "needs_attention" not in g.saved()
    assert g.usage_rows() == []


def test_operator_request_is_a_template_that_flags_the_conversation(g):
    g.canned = "must never be requested"

    g.run({"text": "ოპერატორთან დამაკავშირეთ"})

    assert g.requests == [] and g.usage_rows() == []
    assert g.sent == [HANDOFF_REPLY]
    saved = g.saved()
    assert saved["needs_attention"] is True
    assert saved["messages"][-1] == {"role": "bot", "content": HANDOFF_REPLY}


def test_greeting_with_a_question_goes_to_the_model_with_the_full_shop_block(g):
    g.canned = "წითელი მაისური გვაქვს — 89 ₾. 😊"

    request = g.run({"text": "გამარჯობა, წითელი მაისური გაქვთ?"})

    assert len(g.requests) == 1 and g.history_turns(request) == []
    assert g.final_texts(request)[-1] == "გამარჯობა, წითელი მაისური გაქვთ?"
    l2 = g.layer2(request)
    assert "Shop name: ტესტ მაღაზია" in l2
    assert "Currency: GEL" in l2
    assert "- წითელი მაისური — 89 GEL, in stock: 3" in l2
    assert "- შავი ჯინსი — 120 GEL, in stock: 5" in l2
    assert "Language rule: Reply in the language the customer writes in" in l2
    assert g.sent == ["წითელი მაისური გვაქვს — 89 ₾. 😊"]
    _assert_usage_recorded(g)


# --- (3) a plain answer: one request, tools declared -------------------------------------------
def test_price_question_with_history(g):
    g.seed_history([
        {"role": "user", "content": "გამარჯობა"},
        {"role": "bot", "content": GREETING_REPLY},
    ])
    answer = "წითელი მაისური ღირს 89 ₾ და ხელმისაწვდომია S-XL ზომებში. 😊 გსურთ შეკვეთა?"
    g.canned = answer

    request = g.run({"text": "წითელი მაისური რა ღირს?"})

    assert len(g.requests) == 1
    assert g.tool_names(request) == [t["name"] for t in tools.TOOL_SPECS]
    assert g.sent == [answer]
    assert g.history_turns(request) == [("user", "გამარჯობა"), ("assistant", GREETING_REPLY)]
    assert g.final_texts(request)[-1] == "წითელი მაისური რა ღირს?"
    saved = g.saved()["messages"]
    assert len(saved) == 4  # two old turns + the new pair
    assert saved[-2:] == [
        {"role": "user", "content": "წითელი მაისური რა ღირს?"}, {"role": "bot", "content": answer},
    ]
    assert "needs_attention" not in g.saved()
    _assert_usage_recorded(g)


def test_out_of_stock_product_is_marked_in_the_prompt(g):
    answer = "სამწუხაროდ თეთრი პერანგი ამჟამად არ არის მარაგში. 😊 შავი ჯინსი გვაქვს — 120 ₾."
    g.canned = answer

    request = g.run({"text": "თეთრი პერანგი გაქვთ?"})

    assert g.sent == [answer]
    l2 = g.layer2(request)
    assert "- თეთრი პერანგი — 65 GEL, out of stock, SKU: WHT-1" in l2
    assert "- ტყავის ქურთუკი — 350 GEL, in stock: 1" in l2
    assert g.final_texts(request)[-1] == "თეთრი პერანგი გაქვთ?"
    _assert_usage_recorded(g)


# --- (5) a search round: two requests, only the final text reaches the customer ----------------
def test_search_round_gives_the_result_to_the_model_and_only_the_final_text_to_the_customer(g):
    answer = "დიახ, შავი ჯინსი გვაქვს — 120 ₾, მარაგშია. 😊"
    g.script = [
        g.calls(("s1", "search_products", {"query": "შავი ჯინსი"}), text="ერთი წამით, ვამოწმებ"),
        answer,
    ]

    g.run({"text": "შავი შარვალი გაქვთ?"})

    assert len(g.requests) == 2
    assert g.tool_outputs(g.requests[0]) == []
    (output,) = g.tool_outputs(g.requests[1])
    assert output["id"] == "s1"
    assert "შავი ჯინსი — 120 GEL" in output["content"]
    assert g.sent == [answer]  # the "one moment" preamble of the tool-using answer is not sent
    assert g.saved()["messages"][-1] == {"role": "bot", "content": answer}
    assert "needs_attention" not in g.saved()
    _assert_usage_recorded(g, 2)


# --- (6) request_human: the structured handoff -------------------------------------------------
def test_complaint_request_human_sends_the_operator_phrase_and_flags_the_conversation(g):
    g.script = [g.calls(("h1", "request_human", {"reason": "complaint"}))]

    g.run({"text": COMPLAINT})

    assert len(g.requests) == 1  # request_human ends the turn: no further model call
    assert g.sent == [HANDOFF_REPLY]
    saved = g.saved()
    assert saved["needs_attention"] is True
    assert saved["messages"][-2:] == [
        {"role": "user", "content": COMPLAINT}, {"role": "bot", "content": HANDOFF_REPLY},
    ]
    _assert_usage_recorded(g)


def test_request_human_keeps_the_model_text_when_there_is_one(g):
    text = "ბოდიშს გიხდით! ოპერატორი მალე დაგიკავშირდებათ. 🙏"
    g.script = [g.calls(("h1", "request_human", {"reason": "complaint"}), text=text)]

    g.run({"text": COMPLAINT})

    assert g.sent == [text]
    assert g.saved()["needs_attention"] is True


def test_old_handoff_marker_is_stripped_and_no_longer_flags_the_conversation(g):
    g.canned = "ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏 [[HANDOFF]]"

    g.run({"text": COMPLAINT})

    assert g.sent == [HANDOFF_REPLY]
    assert "[[HANDOFF]]" not in str(g.saved()["messages"])
    assert "needs_attention" not in g.saved()  # the only handoff sources are request_human and the template


# --- (7) postprocess: markdown never reaches Messenger -----------------------------------------
def test_markdown_answer_is_cleaned_before_delivery_and_the_order_link_is_untouched(g):
    order_link = f"https://shop.example.com/panel/order.html?shop={SHOP_ID}"
    g.canned = (
        "# შეთავაზება\n"
        "**წითელი მაისური** — `89 ₾`\n"
        "- ზომები S-XL\n"
        "[დეტალები](https://shop.example.com/items/1)\n"
        f"შეკვეთა: {order_link}"
    )

    g.run({"text": "წითელი მაისური რა ღირს?"})

    (sent,) = g.sent
    assert "**" not in sent and "#" not in sent and "`" not in sent
    assert sent == (
        "შეთავაზება\n"
        "წითელი მაისური — 89 ₾\n"
        "• ზომები S-XL\n"
        "დეტალები: https://shop.example.com/items/1\n"
        f"შეკვეთა: {order_link}"
    )
    assert g.saved()["messages"][-1] == {"role": "bot", "content": sent}  # stored as delivered


# --- (8) photo ---------------------------------------------------------------------------------
def test_photo_without_text_sends_customer_and_reference_images(g):
    answer = "ეს ჩვენი წითელი მაისურია — 89 ₾, მარაგშია. 😊"
    g.canned = answer

    request = g.run({"attachments": [{"type": "image", "payload": {"url": "https://cdn.fb.example/c.jpg"}}]})

    assert len(g.requests) == 1 and g.tool_names(request)
    assert g.sent == [answer]
    texts = g.final_texts(request)
    assert "(The customer sent a photo without text — identify it and answer from the inventory.)" in texts
    assert texts[-1].startswith("(The customer sent a photo without text")

    images = g.final_images(request)
    b64 = lambda raw: base64.b64encode(raw).decode("ascii")  # noqa: E731
    # customer photo first, then the reference photos of the products that have a Storage image
    assert images[0] == b64(CUSTOMER_PHOTO)
    assert b64(b"ref:https://storage.example.com/p1.jpg") in images
    assert b64(b"ref:https://storage.example.com/p3.jpg") in images
    assert len(images) == 3
    assert sorted(g.ref_downloads) == [
        "https://storage.example.com/p1.jpg", "https://storage.example.com/p3.jpg",
    ]
    assert any(t.startswith("• წითელი მაისური — 89") for t in texts)

    assert g.saved()["messages"][-2] == {"role": "user", "content": "[სურათი]"}
    _assert_usage_recorded(g)


def test_greeting_with_a_photo_is_not_answered_by_the_template(g):
    g.canned = "ეს ჩვენი წითელი მაისურია. 😊"

    g.run({"text": "გამარჯობა", "attachments": [{"type": "image", "payload": {"url": "https://cdn.fb.example/c.jpg"}}]})

    assert len(g.requests) == 1
    assert g.sent == ["ეს ჩვენი წითელი მაისურია. 😊"]


# --- (9) the call cap --------------------------------------------------------------------------
def test_call_cap_with_an_empty_final_answer_sends_the_fallback_and_flags_the_conversation(g):
    g.default = lambda n: g.calls((f"c{n}", "search_products", {"query": "ჯინსი"}))

    g.run({"text": "ჯინსი გაქვთ?"})

    assert len(g.requests) == graph.MAX_LLM_CALLS == 4
    none_choice = {"type": "none"} if g.provider == "claude" else "none"
    assert all("tool_choice" not in r for r in g.requests[:3])
    assert g.requests[3]["tool_choice"] == none_choice
    assert g.sent == [webhook.EMPTY_REPLY_FALLBACK]
    saved = g.saved()
    assert saved["needs_attention"] is True
    assert saved["messages"][-1] == {"role": "bot", "content": webhook.EMPTY_REPLY_FALLBACK}
    _assert_usage_recorded(g, 4)


# --- (10) no [[HANDOFF]] anywhere in what the model sees ---------------------------------------
def test_no_request_mentions_the_old_handoff_marker(g):
    g.seed_history([
        {"role": "user", "content": "გამარჯობა"}, {"role": "bot", "content": GREETING_REPLY},
    ])
    g.script = [g.calls(("s1", "search_products", {"query": "მაისური"})), "წითელი მაისური — 89 ₾"]

    g.run({"text": "მაისური გაქვთ?"})

    assert len(g.requests) == 2
    assert "[[HANDOFF]]" not in json.dumps(g.requests, ensure_ascii=False, default=str)
