"""S18-5: customer photo -> (conditional) description -> ranking -> at most 3 reference photos.

Fake Claude / OpenAI SDK clients (tests.test_graph.Harness) wired into the real graph / llm / vision /
prompt modules. Photos are served by a fake download_image. No network, no real key, no .env.
"""
import json
import logging

import pytest

import app.services.facebook as facebook
from app.services import bot, graph, prompt, vision
from tests.test_graph import SHOP, SHOP_ID, Harness

PHOTO_BYTES = 6000
CUSTOMER = [(b"c" * PHOTO_BYTES, "image/jpeg")]
JEANS_DESC = "EN: blue denim jeans with a zip.\nKA: ჯინსი, ლურჯი"

CATALOGUE = [  # id, name, price, image_description
    ("0001", "Red T-shirt", 25, "EN: A red cotton t-shirt with a round neck.\nKA: მაისური, წითელი, ბამბა"),
    ("0002", "Blue Jeans", 80, "EN: Blue denim jeans, straight cut.\nKA: ჯინსი, ლურჯი, დენიმი"),
    ("0003", "Black Jacket", 150, "EN: A black leather jacket with a zip.\nKA: ქურთუკი, შავი, ტყავი"),
    ("0004", "White Sneakers", 120, "EN: White leather sneakers with laces.\nKA: ბოტასი, თეთრი"),
    ("0005", "Green Cap", 20, "EN: A green baseball cap.\nKA: ქუდი, მწვანე"),
    ("0006", "Black Bag", 60, "EN: A black shoulder bag.\nKA: ჩანთა, შავი"),
]


def _url(pid):
    return f"https://cdn.example.com/{pid}.jpg"


def described_products(extra=()):
    rows = [*CATALOGUE, *extra]
    return [
        {"id": pid, "name": name, "price": price, "quantity": 3, "sku": f"S{pid}", "description": "",
         "image_url": _url(pid), "image_description": desc}
        for pid, name, price, desc in rows
    ]


def plain_photo_products(n):
    return [
        {"id": f"{i:04d}", "name": f"Item {i}", "price": 10 + i, "quantity": 2, "sku": f"S{i}",
         "description": f"desc {i}", "image_url": _url(f"{i:04d}")}
        for i in range(n)
    ]


@pytest.fixture
def h(monkeypatch):
    return Harness(monkeypatch)


@pytest.fixture
def ho(monkeypatch):
    return Harness(monkeypatch, "openai", llm_provider="openai", openai_api_key="test-openai-key-not-real")


@pytest.fixture
def downloads(monkeypatch):
    urls = []

    def fake_download(url, **kwargs):
        urls.append(url)
        return b"r" * PHOTO_BYTES, "image/jpeg"

    monkeypatch.setattr(facebook, "download_image", fake_download)
    monkeypatch.setattr(facebook, "is_own_storage_image_url", lambda url: True)
    return urls


def run(message="", products=None, **kwargs):
    kwargs.setdefault("images", CUSTOMER)
    return graph.run_turn(SHOP, described_products() if products is None else products, message, **kwargs)


def describe_requests(h):
    return [r for r in h.requests if "tools" not in r]


def agent_requests(h):
    return [r for r in h.requests if "tools" in r]


def blocks(request):
    return request["messages"][-1]["content"]


def labels(request):
    return [b["text"] for b in blocks(request) if b["type"] == "text" and b["text"].startswith("• ")]


def image_blocks(request):
    return [b for b in blocks(request) if b["type"] == "image"]


def base64_bytes(request):
    return sum(len(b["source"]["data"]) for b in image_blocks(request))


def relevant_block(request):
    return next(b["text"] for b in blocks(request) if b["type"] == "text"
                and b["text"].startswith("Relevant products for this message"))


# ---------------------------------------------------------------------------
# wants_photo_description
# ---------------------------------------------------------------------------
def test_wants_photo_description_needs_more_than_three_described_products():
    products = described_products()
    assert graph.wants_photo_description(products) is True
    assert graph.wants_photo_description(products[:4]) is True
    assert graph.wants_photo_description(products[:bot.MAX_REF_IMAGES]) is False
    assert graph.wants_photo_description([]) is False
    assert graph.wants_photo_description(None) is False


def test_wants_photo_description_ignores_empty_blank_and_missing_descriptions():
    products = described_products()[:3]
    products += [{"id": "x1", "name": "A", "image_description": None},
                 {"id": "x2", "name": "B", "image_description": ""},
                 {"id": "x3", "name": "C", "image_description": "   \n"},
                 {"id": "x4", "name": "D"}]
    assert graph.wants_photo_description(products) is False
    assert graph.wants_photo_description([*products, described_products()[3]]) is True


# ---------------------------------------------------------------------------
# build_turn_prompt
# ---------------------------------------------------------------------------
def test_build_turn_prompt_hands_ranked_candidates_to_the_loader():
    seen = []

    def loader(ranked, images):
        seen.append(ranked)
        return []

    graph.build_turn_prompt(SHOP, described_products(), "", None, CUSTOMER, refs_loader=loader,
                            photo_description=JEANS_DESC)
    (ranked,) = seen
    assert ranked[0]["name"] == "Blue Jeans"
    assert len(ranked) == 6  # the loader (bot._fetch_product_images) applies the <=3 cap


def test_build_turn_prompt_ignores_the_description_without_a_customer_photo():
    products = described_products()
    called = []
    built = graph.build_turn_prompt(SHOP, products, "Blue Jeans", None, None, refs_loader=called.append,
                                    photo_description=JEANS_DESC)
    assert built == prompt.build_prompt(SHOP, products, "Blue Jeans", None, None, None)
    assert called == []


def test_build_turn_prompt_without_description_ranks_by_message_text():
    seen = []
    graph.build_turn_prompt(SHOP, described_products(), "black", None, CUSTOMER,
                            refs_loader=lambda ranked, images: seen.append(ranked) or [])
    assert [p["name"] for p in seen[0][:2]] == ["Black Jacket", "Black Bag"]


# ---------------------------------------------------------------------------
# (1) the main flow
# ---------------------------------------------------------------------------
def test_photo_with_empty_text_describes_then_sends_three_candidates(h, downloads):
    h.script = [h.text(JEANS_DESC), h.text("This is the Blue Jeans, 80 GEL.")]

    result = run("")

    assert len(h.requests) == 2
    describe, agent = h.requests
    assert "tools" not in describe and describe["max_tokens"] == vision.DESCRIBE_MAX_TOKENS == 300
    assert describe["system"] == [{"type": "text", "text": vision.DESCRIBE_SYSTEM}]
    (content,) = [m["content"] for m in describe["messages"]]
    assert [b["type"] for b in content] == ["image", "text"] and content[1]["text"] == vision.USER_TEXT
    assert len(agent["tools"]) >= 1
    assert len(image_blocks(agent)) == 1 + bot.MAX_REF_IMAGES
    assert len(labels(agent)) == 3 and labels(agent)[0].startswith("• Blue Jeans — 80")
    assert sorted(downloads) == sorted(_url(p) for p in ("0002", "0001", "0003"))  # jeans + next two by sort key
    assert result.text == "This is the Blue Jeans, 80 GEL."
    assert len(result.calls) == 2 and result.calls[0].text == JEANS_DESC  # the description comes first
    assert len(h.usage_rows()) == 2


# ---------------------------------------------------------------------------
# (2) small shops: no description
# ---------------------------------------------------------------------------
def test_three_described_products_skip_the_description_call(h, downloads):
    h.script = [h.text("ok")]
    result = run("", products=described_products()[:3])
    assert len(h.requests) == 1 and describe_requests(h) == []
    assert len(labels(h.requests[0])) == 3 and len(result.calls) == 1
    assert len(h.usage_rows()) == 1


def test_many_photos_but_few_descriptions_skip_the_description_call(h, downloads):
    products = plain_photo_products(8)
    for p in products[:3]:
        p["image_description"] = "EN: a thing\nKA: ნივთი"
    h.script = [h.text("ok")]
    run("", products=products)
    assert describe_requests(h) == [] and len(h.requests) == 1
    assert len(labels(h.requests[0])) == 3


# ---------------------------------------------------------------------------
# (3) measurable reduction
# ---------------------------------------------------------------------------
def test_twelve_photo_products_send_four_images_not_thirteen(h, downloads):
    products = plain_photo_products(12)
    h.script = [h.text("ok"), h.text("ok")]

    run("what is this?", products=products)
    new = h.requests[-1]
    assert describe_requests(h) == [] and len(image_blocks(new)) == 4

    def old_loader(ranked, images):  # the Stage 16 ceiling
        return bot._fetch_product_images(ranked, images, max_images=12)

    run("what is this?", products=products, refs_loader=old_loader)
    old = h.requests[-1]

    assert len(image_blocks(old)) == 13
    assert base64_bytes(new) <= 0.4 * base64_bytes(old)
    print(f"images {len(image_blocks(new))} vs {len(image_blocks(old))}; "
          f"base64 {base64_bytes(new)} vs {base64_bytes(old)} ({base64_bytes(new) / base64_bytes(old):.2f})")


# ---------------------------------------------------------------------------
# (4) the description fails: text ranking, the reply still comes
# ---------------------------------------------------------------------------
FAILURES = {
    "exception": lambda h: ValueError("boom"),
    "timeout": lambda h: TimeoutError("slow"),
    "empty": lambda h: h.text(""),
}


@pytest.mark.parametrize("kind", sorted(FAILURES))
def test_failed_description_falls_back_to_text_ranking(h, downloads, caplog, kind):
    failure = FAILURES[kind](h)
    h.default = lambda n: failure if "tools" not in h.requests[-1] else h.text("It looks like a black item.")

    with caplog.at_level(logging.WARNING, logger="app"):
        result = run("black")

    assert len(agent_requests(h)) == 1 and describe_requests(h)
    assert result.text == "It looks like a black item."
    assert [t.split(" — ")[0] for t in labels(agent_requests(h)[0])][:2] == ["• Black Jacket", "• Black Bag"]
    assert any("image description failed" in r.getMessage() and SHOP_ID in r.getMessage()
               for r in caplog.records if r.levelno == logging.WARNING)
    assert len(result.calls) == (2 if kind == "empty" else 1)  # an empty answer was still billed


# ---------------------------------------------------------------------------
# (5) > 30 products: the description drives retrieval
# ---------------------------------------------------------------------------
def test_big_catalogue_retrieves_the_described_product(h, downloads):
    products = plain_photo_products(40)
    for p in products:
        p["image_description"] = f"EN: a plain grey shirt number {p['id']}.\nKA: მაისური, ნაცრისფერი"
    products[35]["image_description"] = "EN: A black jacket with pockets.\nKA: ქურთუკი, შავი"
    h.script = [h.text("EN: black jacket.\nKA: ქურთუკი, შავი"), h.text("This is Item 35.")]

    run("ეს გაქვთ?", products=products)

    agent = agent_requests(h)[0]
    block = relevant_block(agent)
    assert "- Item 35 —" in block
    assert labels(agent)[0].startswith("• Item 35 —")
    for label in labels(agent):
        assert f"- {label.removeprefix('• ').split(' — ')[0]} —" in block


def test_big_catalogue_without_description_does_not_find_it(h, downloads):
    """control: the same shop with only the generic text has no reason to pick Item 35 (describe call off)."""
    products = plain_photo_products(40)
    products[35]["image_description"] = "EN: A black jacket with pockets.\nKA: ქურთუკი, შავი"
    h.script = [h.text("ok")]
    run("ეს გაქვთ?", products=products)
    assert describe_requests(h) == []  # only one described product
    assert "- Item 35 —" not in relevant_block(h.requests[0])


# ---------------------------------------------------------------------------
# (6) the text still counts
# ---------------------------------------------------------------------------
def test_text_and_description_combine(h, downloads):
    cap = ("0000", "Red Cap", 15, "EN: A red cap.\nKA: ქუდი, წითელი")
    products = described_products(extra=[cap])
    # the text alone: both red items match once, the tie goes to the lower id (the cap)
    seen = []
    graph.build_turn_prompt(SHOP, products, "წითელი", None, CUSTOMER,
                            refs_loader=lambda ranked, images: seen.append(ranked) or [])
    assert seen[0][0]["name"] == "Red Cap"

    h.script = [h.text("EN: a t-shirt.\nKA: მაისური"), h.text("ok")]
    run("წითელი", products=products)
    assert labels(agent_requests(h)[0])[0].startswith("• Red T-shirt — 25")


# ---------------------------------------------------------------------------
# (7) deadlines
# ---------------------------------------------------------------------------
def test_description_deadline_is_inside_the_turn_budget(h, downloads, monkeypatch):
    seen = []
    original = vision.describe_images

    def spy(*args, **kwargs):
        seen.append(kwargs["deadline"])
        return original(*args, **kwargs)

    monkeypatch.setattr(vision, "describe_images", spy)
    h.script = [h.text(JEANS_DESC), h.text("ok")]
    run("")
    now = h.clock.now
    assert len(seen) == 1
    assert seen[0] <= now + graph.TURN_BUDGET_SECONDS and seen[0] <= now + vision.PHOTO_BUDGET_SECONDS
    assert seen[0] == pytest.approx(now + 12.0)


def test_description_deadline_never_passes_the_turn_deadline(h, downloads, monkeypatch):
    seen = []
    original = vision.describe_images

    def spy(*args, **kwargs):
        seen.append(kwargs["deadline"])
        return original(*args, **kwargs)

    monkeypatch.setattr(vision, "describe_images", spy)
    h.script = [h.text(JEANS_DESC), h.text("ok")]
    soon = h.clock.now + 5.0
    state = {
        "shop": SHOP, "products": described_products(), "message": "", "history": None,
        "images": CUSTOMER, "summary": None, "provider": None, "record_usage": True, "refs_loader": None,
        "deadline": soon, "prompt": None, "steps": [], "calls": [], "photo_calls": [], "pending": [],
        "tool_chars": 0, "tools_used": [], "text": "", "handoff": False, "route": "agent",
    }
    update = graph.agent_node(state)
    assert seen == [soon]
    assert len(update["photo_calls"]) == 1 and len(update["calls"]) == 1


# ---------------------------------------------------------------------------
# (8) usage flag, provider
# ---------------------------------------------------------------------------
def test_record_usage_false_writes_no_rows_but_keeps_the_calls(h, downloads):
    h.script = [h.text(JEANS_DESC), h.text("ok")]
    result = run("", record_usage=False)
    assert h.usage_rows() == []
    assert len(result.calls) == 2 and result.calls[0].text == JEANS_DESC


def test_openai_provider_describes_with_openai(ho, downloads):
    ho.script = [ho.text(JEANS_DESC), ho.text("ok")]
    result = run("", provider="openai")
    describe = ho.requests[0]
    user = describe["input"][1]["content"]
    assert user[0]["type"] == "input_image" and user[0]["detail"] == "low"
    assert user[-1] == {"type": "input_text", "text": vision.USER_TEXT}
    assert describe["input"][0]["content"][0]["text"] == vision.DESCRIBE_SYSTEM
    assert describe["store"] is False and "tools" not in describe
    assert len(ho.requests) == 2 and "tools" in ho.requests[1]
    assert len(result.calls) == 2 and {c.provider for c in result.calls} == {"openai"}


# ---------------------------------------------------------------------------
# (9) tool rounds: one description, one photo load
# ---------------------------------------------------------------------------
def test_tool_rounds_describe_and_load_photos_once(h, downloads):
    search = ("c%d", "search_products", {"query": "jacket"})
    h.script = [
        h.text(JEANS_DESC),
        h.calls((search[0] % 1, *search[1:])),
        h.calls((search[0] % 2, *search[1:])),
        h.calls((search[0] % 3, *search[1:])),
        h.text("Final answer"),
    ]
    loads = []

    def loader(ranked, images):
        loads.append(1)
        return bot._fetch_product_images(ranked, images)

    result = run("", refs_loader=loader)

    assert len(describe_requests(h)) == 1 and len(agent_requests(h)) == graph.MAX_LLM_CALLS
    assert len(h.requests) == 5 and len(result.calls) == 5
    assert loads == [1] and len(downloads) == 3
    for request in agent_requests(h):
        assert len(image_blocks_of_any_user_turn(request)) == 4
    assert result.text == "Final answer"


def image_blocks_of_any_user_turn(request):
    return [b for m in request["messages"] if m["role"] == "user" and isinstance(m["content"], list)
            for b in m["content"] if b.get("type") == "image"]


# ---------------------------------------------------------------------------
# (10) privacy, text turns
# ---------------------------------------------------------------------------
def test_description_never_reaches_prompt_logs_or_usage(h, downloads, caplog):
    marker = "zzmarkerqq"
    h.script = [h.text(f"EN: {marker} blue denim jeans.\nKA: ჯინსი, ლურჯი"), h.text("ok")]

    with caplog.at_level(logging.DEBUG, logger="app"):
        result = run("")

    agent = agent_requests(h)[0]
    assert marker not in json.dumps(agent, default=str, ensure_ascii=False)
    assert marker not in json.dumps([row.payload for row in h.usage_rows()], default=str, ensure_ascii=False)
    assert marker not in caplog.text
    assert any("photo=1" in r.getMessage() for r in caplog.records if r.getMessage().startswith("bot turn:"))
    assert labels(agent)[0].startswith("• Blue Jeans")  # ...yet it did drive the ranking
    assert result.calls[0].text.count(marker) == 1  # only the returned LLMResult (turn memory) holds it


def test_text_turn_on_a_described_shop_makes_no_description_call(h):
    products = described_products()
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    h.script = [h.text("ok")]

    result = run("Blue Jeans?", products=products, history=history, images=None)

    assert len(h.requests) == 1 and len(result.calls) == 1
    assert all(b["type"] == "text" for b in blocks(h.requests[0]))
    assert graph.build_turn_prompt(SHOP, products, "Blue Jeans?", history, None, photo_description=JEANS_DESC) \
        == prompt.build_prompt(SHOP, products, "Blue Jeans?", history, None, None)


def test_non_valid_customer_photo_makes_no_description_call(h, downloads):
    h.script = [h.text("ok")]
    run("", images=[(b"x", "image/bmp")])  # not an allowed mime: llm drops it, vision has nothing to describe
    assert describe_requests(h) == [] and len(h.requests) == 1


def test_description_usage_row_belongs_to_the_shop(h, downloads):
    h.script = [h.text(JEANS_DESC), h.text("ok")]
    run("")
    assert [row.payload["shop_id"] for row in h.usage_rows()] == [SHOP_ID, SHOP_ID]
