"""S14-3: three-layer prompt (pure, offline). Layers 1 and 2 must be byte-identical across
messages of the same shop so provider prompt caching hits."""
import random
import uuid
from pathlib import Path

from app.services import prompt as P
from app.services.prompt import (
    LAYER1,
    MAX_PROMPT_CHARS,
    RETRIEVE_LIMIT,
    build_layer2,
    build_prompt,
    normalize_history,
)

SHOP_ID = str(uuid.uuid4())
SHOP = {
    "id": SHOP_ID,
    "name": "Tbilisi Style",
    "description": "Clothes",
    "currency": "GEL",
    "knowledge": "Delivery in Tbilisi: 5 GEL.",
}


def _products(n, prefix="Item"):
    return [
        {"id": f"{i:04d}", "name": f"{prefix} {i}", "price": 10 + i, "quantity": i % 3, "sku": f"S{i}",
         "description": f"desc {i}"}
        for i in range(n)
    ]


def _final_text(prompt):
    return "\n".join(p["text"] for p in prompt.final if p["type"] == "text")


def _total_chars(prompt):
    return (
        len(prompt.layer1) + len(prompt.layer2)
        + sum(len(t["text"]) for t in prompt.history)
        + sum(len(p["text"]) for p in prompt.final if p["type"] == "text")
    )


# (1) owner test: layers 1 and 2 byte-identical across different messages / histories
def _assert_cache_stable(products):
    h1 = [{"role": "user", "content": "hi"}, {"role": "bot", "content": "hello!"}]
    h2 = [{"role": "user", "content": "item 3 price?"}, {"role": "bot", "content": "13 GEL"}]
    a = build_prompt(SHOP, products, "Item 3", history=h1)
    b = build_prompt(SHOP, products, "Item 25 please, size M?", history=h2)
    c = build_prompt(SHOP, products, "hello", history=None)
    for other in (b, c):
        assert a.layer1.encode("utf-8") == other.layer1.encode("utf-8")
        assert a.layer2.encode("utf-8") == other.layer2.encode("utf-8")
    return a, b


def test_layers_byte_identical_small_catalogue():
    a, b = _assert_cache_stable(_products(5))
    assert _final_text(a) != _final_text(b)  # only the customer text differs


def test_layers_byte_identical_large_catalogue_retrieval_differs():
    a, b = _assert_cache_stable(_products(40))
    assert "Relevant products for this message" in _final_text(a)
    assert _final_text(a) != _final_text(b)  # retrieval differs, layer 2 does not


# (2) LAYER1 is a stable, shop-independent constant
def test_layer1_matches_fixture_and_is_static():
    fixture = (Path(__file__).parent / "fixtures" / "prompt_layer1.txt").read_text(encoding="utf-8")
    assert LAYER1 == fixture.replace("\r\n", "\n")
    assert "{" not in LAYER1 and "}" not in LAYER1
    assert len(LAYER1) >= 2600
    assert "[[HANDOFF]]" in LAYER1
    assert "ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏" in LAYER1


# (3) two shops: same layer 1, different layer 2
def test_two_shops_share_layer1_but_not_layer2():
    other = {**SHOP, "id": str(uuid.uuid4()), "name": "Other Shop", "currency": "USD"}
    a = build_prompt(SHOP, _products(3), "hi")
    b = build_prompt(other, _products(3), "hi")
    assert a.layer1 == b.layer1
    assert a.layer2 != b.layer2
    assert "Tbilisi Style" in a.layer2 and "Other Shop" in b.layer2
    assert str(other["id"]) in b.layer2  # per-shop order link


# (4) input order of products does not matter
def test_layer2_independent_of_product_order():
    products = _products(12)
    shuffled = products[:]
    random.Random(7).shuffle(shuffled)
    assert build_layer2(SHOP, products) == build_layer2(SHOP, shuffled)
    assert build_prompt(SHOP, products, "x").layer2 == build_prompt(SHOP, shuffled, "x").layer2


def test_layer2_format():
    products = [
        {"id": "b", "name": "Blue shirt", "price": 65, "quantity": 0, "sku": "BS1", "description": "cotton"},
        {"id": "a", "name": "Red T-shirt", "price": 89, "quantity": 4},
        {"id": "c", "name": "Free gift", "price": 0, "quantity": 2},
    ]
    l2 = build_layer2({**SHOP, "currency": None, "bot_language": "ka"}, products)
    lines = [ln for ln in l2.splitlines() if ln.startswith("- ")]
    assert lines == [
        "- Red T-shirt — 89 GEL, in stock: 4",  # default currency GEL, sorted by id
        "- Blue shirt — 65 GEL, out of stock, SKU: BS1. cotton",
        "- Free gift — price on request, in stock: 2",
    ]
    assert "Always reply in natural, conversational Georgian only." in l2
    assert "/panel/order.html?shop=" in l2
    assert "Delivery in Tbilisi: 5 GEL." in l2


def test_layer2_empty_inventory_and_language_rules():
    assert "(no products available)" in build_layer2(SHOP, [])
    for lang, snippet in (("en", "English only"), ("ru", "Russian only"), ("auto", "conversational Georgian"),
                          ("bogus", "conversational Georgian")):
        assert snippet in build_layer2({**SHOP, "bot_language": lang}, [])


# (5) customer text never reaches layer 2
def test_customer_text_not_in_layer2():
    secret = "ZZ-UNIQUE-CUSTOMER-TEXT-ZZ"
    for products in (_products(5), _products(40)):
        p = build_prompt(SHOP, products, secret, history=[{"role": "user", "content": secret + " old"}])
        assert secret not in p.layer1 and secret not in p.layer2
        assert secret in _final_text(p)
        assert secret in p.history[0]["text"]


# (6) >30 products: layer 2 holds only the count, the relevant subset is in the final turn
def test_large_catalogue_subset_only_in_final():
    products = _products(40)
    products[17]["name"] = "Zebra backpack"
    p = build_prompt(SHOP, products, "zebra backpack")
    assert "The catalogue has 40 products" in p.layer2
    assert not [ln for ln in p.layer2.splitlines() if ln.startswith("- ")]
    assert "Zebra backpack" not in p.layer2
    text = p.final[0]["text"]
    assert text.startswith("Relevant products for this message (1 of 40):")
    assert "- Zebra backpack — 27 GEL" in text


def test_small_catalogue_has_no_retrieval_part():
    p = build_prompt(SHOP, _products(RETRIEVE_LIMIT), "hello")
    assert "Relevant products" not in _final_text(p)
    assert [x["text"] for x in p.final] == ["hello"]
    assert "- Item 0 — 10 GEL, out of stock" in p.layer2


def test_select_relevant_products_unchanged_semantics():
    products = _products(40)
    assert P.select_relevant_products(products[:5], "x") == products[:5]
    assert P.select_relevant_products(products, "მინდა გინდა") == products[:RETRIEVE_LIMIT]  # stopwords only
    assert P.select_relevant_products(products, "nothing-matches-here") == products[:RETRIEVE_LIMIT]
    assert P.select_relevant_products(products, "Item 33") [0]["name"] == "Item 33"
    hist = [{"role": "user", "content": "Item 7"}, {"role": "bot", "content": "ok"}]
    assert any(x["name"] == "Item 7" for x in P.select_relevant_products(products, "x y", hist))


# (7) normalize_history
def test_normalize_history_cases():
    assert normalize_history(None) == []
    assert normalize_history([]) == []
    h = [
        {"role": "bot", "content": "leading bot greeting"},
        {"role": "bot", "content": "second bot"},
        {"role": "user", "content": "  hi  "},
        {"role": "user", "content": "one more"},
        {"role": "bot", "content": "   "},  # empty -> dropped
        {"role": "bot", "content": "hello"},
        {"role": "weird", "content": "treated as assistant"},
        {"role": "user", "content": None},  # dropped
        "garbage",
        {"role": "user", "content": "last"},
    ]
    assert normalize_history(h) == [
        {"role": "user", "text": "hi\n\none more"},
        {"role": "assistant", "text": "hello\n\ntreated as assistant"},
        {"role": "user", "text": "last"},
    ]
    assert normalize_history([{"role": "bot", "content": "only bot"}]) == []
    # empty turn between same-role neighbours: they merge
    assert normalize_history([
        {"role": "user", "content": "a"}, {"role": "bot", "content": ""}, {"role": "user", "content": "b"},
    ]) == [{"role": "user", "text": "a\n\nb"}]


# (8) worst case: the total stays bounded, only history is trimmed
def _huge_case(n_products):
    huge = "x" * 100_000
    shop = {**SHOP, "name": huge, "description": "d" * 1_000_000, "knowledge": "k" * 1_000_000}
    products = [
        {"id": f"{i:03d}", "name": huge, "sku": huge, "description": huge, "price": 10, "quantity": 1}
        for i in range(n_products)
    ]
    history = []
    for i in range(20):
        history.append({"role": "user", "content": f"u{i} " + "q" * 2000})
        history.append({"role": "bot", "content": f"b{i} " + "a" * 2000})
    return shop, products, history


def test_worst_case_30_products_total_bounded():
    # 30 maximal products + 20000-char knowledge + max shop name/description + 20 x 2000 history
    shop, products, history = _huge_case(30)
    p = build_prompt(shop, products, "m" * 2000, history=history)
    assert p.layer1 == LAYER1
    assert p.layer2 == build_layer2(shop, products)  # untouched by trimming
    assert _final_text(p) == "m" * 2000
    assert _total_chars(p) <= MAX_PROMPT_CHARS
    assert not p.history or p.history[0]["role"] == "user"


def test_worst_case_40_products_total_bounded():
    # >30 products: up to 30 maximal relevant products go into the final turn instead of layer 2
    shop, products, history = _huge_case(40)
    p = build_prompt(shop, products, "m" * 2000, history=history)
    assert p.layer2 == build_layer2(shop, products)
    assert p.final[0]["text"].startswith("Relevant products for this message (30 of 40):")
    assert p.final[-1] == {"type": "text", "text": "m" * 2000}
    assert _total_chars(p) <= MAX_PROMPT_CHARS
    assert not p.history or p.history[0]["role"] == "user"


def test_worst_case_with_room_keeps_newest_history():
    shop, products, history = _huge_case(10)
    p = build_prompt(shop, products, "m" * 2000, history=history)
    assert _total_chars(p) <= MAX_PROMPT_CHARS
    assert 0 < len(p.history) < 40  # trimmed, not dropped
    assert p.history[0]["role"] == "user"
    assert p.history[-1]["text"].startswith("b19 ")  # the newest turns are the ones kept


def test_history_trimmed_oldest_first_and_user_first():
    layer_chars = len(LAYER1) + len(build_layer2(SHOP, _products(3))) + len("hi")
    room = MAX_PROMPT_CHARS - layer_chars
    # 10 turns of ~room/4 chars: only the newest ~3 fit; the kept tail must start with a user turn
    size = room // 4
    history = []
    for i in range(10):
        history.append({"role": "user", "content": f"U{i:02d}" + "q" * size})
        history.append({"role": "bot", "content": f"B{i:02d}" + "a" * size})
    p = build_prompt(SHOP, _products(3), "hi", history=history)
    assert 0 < len(p.history) < 20
    assert p.history[0]["role"] == "user"
    assert p.history[-1]["text"].startswith("B09")  # newest kept
    assert _total_chars(p) <= MAX_PROMPT_CHARS
    kept_first = int(p.history[0]["text"][1:3])
    assert [t["text"][:3] for t in p.history][:2] == [f"U{kept_first:02d}", f"B{kept_first:02d}"]


def test_small_history_untouched():
    h = [{"role": "user", "content": "hi"}, {"role": "bot", "content": "hello"}]
    assert build_prompt(SHOP, _products(2), "x", history=h).history == [
        {"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello"},
    ]


# (9) final turn ordering with photos / reference photos
def test_final_order_photos_refs_then_text():
    products = _products(40)
    images = [(b"img1", "image/jpeg"), (b"img2", "image/png")]
    refs = [("• Item 3 — 13", (b"ref1", "image/jpeg")), ("• Item 4 — 14", (b"ref2", "image/webp"))]
    p = build_prompt(SHOP, products, "Item 3 or Item 4?", images=images, product_refs=refs)
    kinds = [x["type"] for x in p.final]
    assert kinds == ["text", "text", "image", "image", "text", "text", "image", "text", "image", "text"]
    assert p.final[0]["text"].startswith("Relevant products for this message (")
    assert p.final[2] == {"type": "image", "data": b"img1", "mime": "image/jpeg"}
    assert p.final[3]["data"] == b"img2"
    assert p.final[5]["text"] == "• Item 3 — 13"
    assert p.final[6]["data"] == b"ref1"
    assert p.final[7]["text"] == "• Item 4 — 14"
    assert p.final[8] == {"type": "image", "data": b"ref2", "mime": "image/webp"}
    assert p.final[-1] == {"type": "text", "text": "Item 3 or Item 4?"}


def test_photo_without_text_uses_placeholder():
    p = build_prompt(SHOP, _products(3), "   ", images=[(b"img", "image/jpeg")])
    assert [x["type"] for x in p.final] == ["text", "image", "text"]
    assert p.final[-1]["text"] == "(The customer sent a photo without text — identify it and answer from the inventory.)"


def test_broken_images_skipped_and_empty_message_has_text():
    p = build_prompt(SHOP, _products(3), "hi", images=["junk", (None, "image/jpeg"), (b"ok", "image/png")],
                     product_refs=[("label", "junk"), ("label2", (b"", "image/png"))])
    assert [x["type"] for x in p.final] == ["text", "image", "text"]
    assert p.final[1]["data"] == b"ok"
    empty = build_prompt(SHOP, _products(3), "")
    assert len(empty.final) == 1 and empty.final[0]["type"] == "text" and empty.final[0]["text"]


def test_module_has_no_provider_imports():
    src = Path(P.__file__).read_text(encoding="utf-8")
    for banned in ("import google", "from google", "import anthropic", "from anthropic",
                   "import openai", "from openai", "import httpx", "import requests"):
        assert banned not in src
