"""S14-6: Georgian golden conversations, end to end, for both providers (offline).

Real chain: webhook._process_events -> get_bot_reply -> prompt -> llm, with fake Claude / OpenAI
SDK clients (canned model output), a fake service DB, and patched Facebook I/O. Checks what
the customer receives, what the model request contains, and what the webhook stores.
"""
import base64
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.api.webhook as webhook
import app.services.bot as bot
import app.services.facebook as facebook
import app.services.llm as llm
from tests.test_reply_delivery import PAGE_ID, PSID, SHOP_ID

GREETING_REPLY = "გამარჯობა! 😊 რით შემიძლია დაგეხმაროთ?"
HANDOFF_REPLY = "ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏"
CUSTOMER_PHOTO = b"customer-photo-bytes"

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
    """Wires fake provider clients and a fake DB into the real webhook -> bot -> prompt -> llm chain."""

    def __init__(self, provider, monkeypatch, db):
        self.provider = provider
        self.db = db
        self.requests: list[dict] = []
        self.sent: list[str] = []
        self.canned = ""
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
            return SimpleNamespace(
                content=[
                    SimpleNamespace(type="thinking", thinking="(model reasoning, never shown)"),
                    SimpleNamespace(type="text", text=self.canned),
                ],
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=120, output_tokens=18, cache_read_input_tokens=900,
                                      cache_creation_input_tokens=0),
            )

        def openai_create(**kwargs):
            self.requests.append(kwargs)
            return SimpleNamespace(
                output_text=self.canned,
                usage=SimpleNamespace(input_tokens=1020, output_tokens=18,
                                      input_tokens_details=SimpleNamespace(cached_tokens=900)),
            )

        monkeypatch.setattr(
            llm, "_anthropic_client", lambda s: SimpleNamespace(messages=SimpleNamespace(create=claude_create)))
        monkeypatch.setattr(
            llm, "_openai_client", lambda s: SimpleNamespace(responses=SimpleNamespace(create=openai_create)))

    # --- webhook side ---------------------------------------------------------------------
    def seed_history(self, turns):
        self.db.responses[("bot_conversations", "select")] = [{
            "messages": turns, "updated_at": datetime.now(timezone.utc).isoformat(),
        }]

    def run(self, message):
        webhook._process_events({"object": "page", "entry": [{
            "id": PAGE_ID, "messaging": [{"sender": {"id": PSID}, "message": message}],
        }]})
        assert len(self.requests) == 1, "exactly one LLM request per customer message"
        return self.requests[0]

    # --- provider-neutral views of a request ---------------------------------------------
    def layer2(self, request):
        if self.provider == "claude":
            return request["system"][1]["text"]
        return request["input"][0]["content"][1]["text"]

    def history_turns(self, request):
        """Everything before the final user turn, as (role, text)."""
        turns = request["messages"] if self.provider == "claude" else request["input"][1:]
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

    def usage_rows(self):
        return [c.payload for c in self.db.calls_for("llm_usage", "insert")]

    def saved(self):
        (save,) = self.db.calls_for("bot_conversations", "upsert")
        return save.payload


@pytest.fixture(params=["claude", "openai"])
def g(request, monkeypatch, service_db):
    return Golden(request.param, monkeypatch, service_db)


def _assert_usage_recorded(g):
    rows = g.usage_rows()
    assert len(rows) == 1
    assert rows[0]["shop_id"] == SHOP_ID
    assert rows[0]["provider"] == g.provider
    assert rows[0]["model"] == g.settings.llm_model
    assert rows[0]["output_tokens"] == 18
    assert rows[0]["cache_read_tokens"] == 900


def test_greeting(g):
    g.canned = GREETING_REPLY

    request = g.run({"text": "გამარჯობა"})

    assert g.sent == [GREETING_REPLY]  # delivered unchanged
    assert g.history_turns(request) == []
    assert g.final_texts(request)[-1] == "გამარჯობა"
    l2 = g.layer2(request)
    assert "Shop name: ტესტ მაღაზია" in l2
    assert "Currency: GEL" in l2
    assert "- წითელი მაისური — 89 GEL, in stock: 3" in l2
    assert "- შავი ჯინსი — 120 GEL, in stock: 5" in l2
    assert "Language rule: Reply in the language the customer writes in" in l2
    assert g.saved()["messages"] == [
        {"role": "user", "content": "გამარჯობა"}, {"role": "bot", "content": GREETING_REPLY},
    ]
    assert "needs_attention" not in g.saved()
    _assert_usage_recorded(g)


def test_price_question_with_history(g):
    g.seed_history([
        {"role": "user", "content": "გამარჯობა"},
        {"role": "bot", "content": GREETING_REPLY},
    ])
    answer = "წითელი მაისური ღირს 89 ₾ და ხელმისაწვდომია S-XL ზომებში. 😊 გსურთ შეკვეთა?"
    g.canned = answer

    request = g.run({"text": "წითელი მაისური რა ღირს?"})

    assert g.sent == [answer]
    assert g.history_turns(request) == [("user", "გამარჯობა"), ("assistant", GREETING_REPLY)]
    assert g.final_texts(request)[-1] == "წითელი მაისური რა ღირს?"
    saved = g.saved()["messages"]
    assert len(saved) == 4  # two old turns + the new pair
    assert saved[-2:] == [
        {"role": "user", "content": "წითელი მაისური რა ღირს?"}, {"role": "bot", "content": answer},
    ]
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


def test_operator_request_strips_marker_and_flags_conversation(g):
    g.canned = HANDOFF_REPLY + " [[HANDOFF]]"

    g.run({"text": "ოპერატორთან დამაკავშირეთ"})

    assert g.sent == [HANDOFF_REPLY]
    assert not any("[[HANDOFF]]" in t for t in g.sent)
    saved = g.saved()
    assert saved["needs_attention"] is True
    assert saved["messages"][-1] == {"role": "bot", "content": HANDOFF_REPLY}
    assert "[[HANDOFF]]" not in str(saved["messages"])
    _assert_usage_recorded(g)


def test_photo_without_text_sends_customer_and_reference_images(g):
    answer = "ეს ჩვენი წითელი მაისურია — 89 ₾, მარაგშია. 😊"
    g.canned = answer

    request = g.run({"attachments": [{"type": "image", "payload": {"url": "https://cdn.fb.example/c.jpg"}}]})

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
