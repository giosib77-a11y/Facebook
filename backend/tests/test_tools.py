"""S16-4: bot tools — static specs, executors, tenant isolation (pure, offline)."""
import importlib
import json
import uuid
from pathlib import Path

import pytest

from app.services import prompt, tools
from app.services.tools import (
    HUMAN_TOOL,
    TOOL_RESULT_MAX_CHARS,
    TOOL_SPECS,
    ToolContext,
    ToolOutcome,
    execute,
)

SHOP_A_ID = str(uuid.uuid4())
SHOP_B_ID = str(uuid.uuid4())

SHOP_A = {"id": SHOP_A_ID, "name": "Alpha Store", "currency": "GEL",
          "knowledge": "Delivery in Tbilisi: 5 GEL.\n\nReturns within 14 days."}
SHOP_B = {"id": SHOP_B_ID, "name": "Bravo Store", "currency": "USD",
          "knowledge": "Bravo secret warranty: 99 years."}

PRODUCTS_A = [
    {"id": "a1", "name": "Red shirt", "price": 89, "quantity": 3, "sku": "RS1", "description": "cotton"},
    {"id": "a2", "name": "Blue jeans", "price": 120, "quantity": 0},
]
PRODUCTS_B = [
    {"id": "b1", "name": "Zebra backpack", "price": 50, "quantity": 2, "sku": "ZB9"},
]


def ctx_a():
    return ToolContext(shop=SHOP_A, products=PRODUCTS_A)


def ctx_b():
    return ToolContext(shop=SHOP_B, products=PRODUCTS_B)


def ok(name, args, ctx):
    out = execute(name, args, ctx)
    assert isinstance(out, ToolOutcome)
    assert not out.is_error, out.content
    assert len(out.content) <= TOOL_RESULT_MAX_CHARS
    return out.content


def err(name, args, ctx):
    out = execute(name, args, ctx)
    assert out.is_error is True
    assert out.content.startswith("Error:")
    return out.content


# --- specs ---------------------------------------------------------------------------------
def test_spec_order_and_names():
    assert [s["name"] for s in TOOL_SPECS] == ["search_products", "search_knowledge", "order_link", "request_human"]
    assert HUMAN_TOOL == "request_human"
    for s in TOOL_SPECS:
        assert set(s) == {"name", "description", "parameters"}
        assert s["description"].strip()


def test_specs_are_static_and_shop_independent():
    first = json.dumps(TOOL_SPECS, ensure_ascii=False, sort_keys=False)
    # calling the executors in between must not mutate the specs
    execute("search_products", {"query": "shirt"}, ctx_a())
    execute("order_link", {}, ctx_b())
    assert json.dumps(TOOL_SPECS, ensure_ascii=False, sort_keys=False) == first
    assert len(first) <= 3000
    for needle in ("Alpha", "Bravo", "GEL", "USD", "http", "/panel/", SHOP_A_ID, SHOP_B_ID):
        assert needle not in first
    assert "shop_id" not in first and "{{" not in first


def test_specs_are_strict_compatible():
    for s in TOOL_SPECS:
        params = s["parameters"]
        assert params["type"] == "object"
        assert params["additionalProperties"] is False
        assert params["required"] == list(params["properties"])
    props = {s["name"]: s["parameters"]["properties"] for s in TOOL_SPECS}
    assert props["search_products"]["query"]["type"] == "string"
    assert props["search_knowledge"]["query"]["type"] == "string"
    assert props["order_link"] == {}
    assert props["request_human"]["reason"]["enum"] == ["customer_request", "complaint", "cannot_help", "other"]


# --- tenant isolation ----------------------------------------------------------------------
def test_other_shop_product_not_found_with_my_context():
    assert "Zebra" in ok("search_products", {"query": "zebra backpack"}, ctx_b())
    out = ok("search_products", {"query": "zebra backpack"}, ctx_a())
    assert "Zebra" not in out and "ZB9" not in out
    assert out.startswith('No products match "zebra backpack"')


def test_other_shop_knowledge_and_link_not_reachable():
    assert "99 years" in ok("search_knowledge", {"query": "warranty"}, ctx_b())
    assert "99 years" not in ok("search_knowledge", {"query": "bravo secret warranty"}, ctx_a())
    assert SHOP_B_ID not in ok("order_link", {}, ctx_a())


@pytest.mark.parametrize("name", ["search_products", "search_knowledge"])
def test_shop_id_argument_is_rejected(name):
    err(name, {"query": "x", "shop_id": SHOP_B_ID}, ctx_a())
    err(name, {"shop_id": SHOP_B_ID}, ctx_a())
    err(name, {"query": "x", "extra": 1}, ctx_a())


def test_order_link_rejects_any_argument():
    err("order_link", {"shop_id": SHOP_B_ID}, ctx_a())
    err("order_link", {"query": "x"}, ctx_a())


def test_executors_never_touch_the_database(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("tool executors must not use a DB client")

    patched = 0
    for mod_name in ("app.core.supabase_client", "app.services.llm", "app.api.webhook", "app.api.chat",
                     "app.api.products", "app.api.shops", "app.api.admin", "app.api.facebook", "app.api.orders"):
        mod = importlib.import_module(mod_name)
        if hasattr(mod, "get_service_client"):
            monkeypatch.setattr(mod, "get_service_client", boom)
            patched += 1
    assert patched >= 5  # the patch really covers the modules that import the service client
    assert "Red shirt" in ok("search_products", {"query": "red shirt"}, ctx_a())
    assert "Delivery" in ok("search_knowledge", {"query": "delivery"}, ctx_a())
    assert "Order link" in ok("order_link", {}, ctx_a())


def test_tools_module_imports_nothing_forbidden():
    src = Path(tools.__file__).read_text(encoding="utf-8")
    for banned in ("anthropic", "openai", "langgraph", "langchain", "httpx", "supabase",
                   "get_service_client", "app.services.llm"):
        assert banned not in src


# --- search_products -----------------------------------------------------------------------
def test_search_products_result_format():
    out = ok("search_products", {"query": "  red shirt "}, ctx_a())
    assert out == (
        'Products matching "red shirt" (1 of 2 in the catalogue):\n'
        "- Red shirt — 89 GEL, in stock: 3, SKU: RS1. cotton"
    )


def test_search_products_uses_shop_currency():
    out = ok("search_products", {"query": "zebra"}, ctx_b())
    assert "50 USD" in out and "GEL" not in out


def test_search_products_limit_10_and_size_cap():
    products = [{"id": f"{i:03d}", "name": f"Shirt {i}", "price": 5, "quantity": 1,
                 "description": "d" * 600} for i in range(40)]
    out = ok("search_products", {"query": "shirt"}, ToolContext(shop=SHOP_A, products=products))
    assert out.startswith('Products matching "shirt" (10 of 40 in the catalogue):')
    assert out.endswith("…")  # 10 x ~650 chars is cut at a line boundary
    assert len(out) <= TOOL_RESULT_MAX_CHARS
    assert out.splitlines()[1].startswith("- Shirt 0 —")  # best-first, ties in id order


def test_search_products_empty_results():
    assert execute("search_products", {"query": "zebra"}, ctx_a()).content == \
        'No products match "zebra". The catalogue has 2 products.'
    empty = execute("search_products", {"query": "zebra"}, ToolContext(shop=SHOP_A, products=[]))
    assert empty.content == 'No products match "zebra". The catalogue has 0 products.' and not empty.is_error
    stop = execute("search_products", {"query": "და რა"}, ctx_a())  # only stopwords -> no tokens
    assert stop.content.startswith('No products match "და რა"') and not stop.is_error


def test_search_products_query_is_echoed_truncated():
    q = "zebra" + "x" * 190
    out = ok("search_products", {"query": q}, ctx_a())
    assert out == f'No products match "{q[:100]}". The catalogue has 2 products.'


# --- search_knowledge ----------------------------------------------------------------------
def test_search_knowledge_returns_matching_paragraph():
    out = ok("search_knowledge", {"query": "delivery tbilisi"}, ctx_a())
    assert out == 'Shop knowledge excerpts for "delivery tbilisi":\nDelivery in Tbilisi: 5 GEL.'


def test_search_knowledge_finds_text_beyond_the_20000_char_clip():
    filler = "\n\n".join(f"Filler paragraph number {i} about nothing." for i in range(1200))
    assert len(filler) > 20_000
    shop = {**SHOP_A, "knowledge": filler + "\n\nThe quokka policy: free quokka returns."}
    assert "quokka" not in prompt.build_layer2(shop, [])  # clipped out of the SHOP block
    out = ok("search_knowledge", {"query": "quokka"}, ToolContext(shop=shop, products=[]))
    assert "The quokka policy: free quokka returns." in out


def test_search_knowledge_top3_by_score_then_position():
    knowledge = "\n\n".join([
        "alpha one",             # 0: score 1
        "alpha beta two",        # 1: score 2
        "alpha beta three",      # 2: score 2
        "alpha beta gamma four",  # 3: score 3
        "alpha five",            # 4: score 1
    ])
    shop = {**SHOP_A, "knowledge": knowledge}
    out = ok("search_knowledge", {"query": "alpha beta gamma"}, ToolContext(shop=shop, products=[]))
    body = out.split("\n", 1)[1]
    assert body.split("\n---\n") == ["alpha beta gamma four", "alpha beta two", "alpha beta three"]


def test_search_knowledge_long_paragraph_is_split_into_windows():
    para = ("start " + "w" * 794) + ("needle " + "z" * 793)  # one 1600-char paragraph, no blank lines
    shop = {**SHOP_A, "knowledge": para}
    out = ok("search_knowledge", {"query": "needle"}, ToolContext(shop=shop, products=[]))
    body = out.split("\n", 1)[1]
    assert "\n---\n" not in body and len(body) <= 800  # only the window that contains the word


def test_search_knowledge_size_cap_with_huge_knowledge():
    knowledge = "\n\n".join("common " + "y" * 3000 for _ in range(20))
    shop = {**SHOP_A, "knowledge": knowledge}
    out = ok("search_knowledge", {"query": "common"}, ToolContext(shop=shop, products=[]))
    assert out.count("\n---\n") == 2  # top 3 windows of <= 800 chars
    assert len(out) <= TOOL_RESULT_MAX_CHARS


def test_search_knowledge_empty_results():
    assert execute("search_knowledge", {"query": "zebra"}, ctx_a()).content == \
        "No matching information in the shop knowledge."
    assert execute("search_knowledge", {"query": "და რა"}, ctx_a()).content == \
        "No matching information in the shop knowledge."
    for knowledge in (None, "", "   \n\n ", 5):
        out = execute("search_knowledge", {"query": "delivery"},
                      ToolContext(shop={**SHOP_A, "knowledge": knowledge}, products=[]))
        assert out.content == "The shop has no knowledge document." and not out.is_error


# --- S17-5: line-based chunks + Georgian stems ----------------------------------------------
def _knowledge_ctx(knowledge):
    return ToolContext(shop={**SHOP_A, "knowledge": knowledge}, products=[])


def _body(out):
    return out.split("\n", 1)[1]


KA_KNOWLEDGE = "\n\n".join([
    "მიწოდების პირობები: თბილისში 5 ლარი.",
    "პროდუქტის გარანტიის ვადა 2 წელია.",
    "დაბრუნება შესაძლებელია 14 დღის განმავლობაში.",
])


@pytest.mark.parametrize("query, expected", [
    ("მიწოდება", "მიწოდების პირობები: თბილისში 5 ლარი."),   # nominative query, genitive text
    ("გარანტია", "პროდუქტის გარანტიის ვადა 2 წელია."),
    ("დაბრუნება", "დაბრუნება შესაძლებელია 14 დღის განმავლობაში."),
])
def test_search_knowledge_georgian_stem_matches_other_case_forms(query, expected):
    out = ok("search_knowledge", {"query": query}, _knowledge_ctx(KA_KNOWLEDGE))
    assert _body(out) == expected


def test_search_knowledge_georgian_locative_query_matches_nominative_text():
    knowledge = "მიწოდება თბილისი და რეგიონები: 5 ლარი.\n\nდაბრუნება 14 დღე."
    out = ok("search_knowledge", {"query": "თბილისში"}, _knowledge_ctx(knowledge))
    assert _body(out) == "მიწოდება თბილისი და რეგიონები: 5 ლარი."


@pytest.mark.parametrize("token, stem", [
    ("ლარი", "ლარი"),            # < 6 chars: unchanged
    ("დღეები", "დღეე"),           # 6 chars: len - 2 = 4
    ("მიწოდება", "მიწოდე"),       # 8 chars -> 6
    ("მიწოდების", "მიწოდებ"),
    ("warranty", "warran"),
    ("short", "short"),
])
def test_stem_rule(token, stem):
    assert tools._stem(token) == stem


def test_search_knowledge_stem_does_not_match_unrelated_words():
    out = execute("search_knowledge", {"query": "მიწოდება"}, _knowledge_ctx("დაბრუნება 14 დღე.\n\nგარანტია 2 წელი."))
    assert out.content == "No matching information in the shop knowledge."


def test_search_knowledge_long_paragraph_keeps_whole_lines():
    lines = [f"line{i:02d} " + "w" * 98 for i in range(30)]  # 105 chars each, one paragraph, no blank lines
    marked = 7  # starts at offset 742, so the old 800-char window cut it in the middle
    lines[marked] = lines[marked][:-10] + "zetamarker"
    assert len(lines[marked]) == 105
    out = ok("search_knowledge", {"query": "zetamarker"}, _knowledge_ctx("\n".join(lines)))
    body = _body(out)
    assert lines[marked] in body.split("\n")
    assert len(body) <= 800 and "\n---\n" not in body
    assert all(line in lines for line in body.split("\n"))  # no line is cut


def test_knowledge_chunks_rules():
    window = tools._KNOWLEDGE_WINDOW
    short = "a" * 300
    assert tools._knowledge_chunks(f"{short}\n\n{short}b\n \n{short}c") == [short, short + "b", short + "c"]
    para = "\n".join(f"{i:02d}" + "x" * 98 for i in range(20))  # 20 lines of 100 chars, 1999 chars
    chunks = tools._knowledge_chunks(para)
    assert all(len(c) <= window for c in chunks)
    assert "\n".join(chunks) == para  # nothing lost, nothing cut, order kept
    assert [len(c) for c in chunks] == [706, 706, 605]  # 7 + 7 + 6 lines (an 8th line would make 807)
    long_line = "y" * 1700
    assert tools._knowledge_chunks(f"head\n{long_line}\ntail") == ["head", "y" * 800, "y" * 800, "y" * 100, "tail"]


def test_search_knowledge_finds_a_marker_deep_in_a_50000_char_document():
    head = [f"Filler line {i:05d} about nothing at all." for i in range(1220)]
    text = "\n".join(head)
    assert 48_000 < len(text) < 49_500
    text += "\nThe quokka clause: free quokka returns.\n"
    text += "\n".join(f"Tail line {i:05d} about nothing." for i in range(100))
    text = text[:50_000]
    assert len(text) == 50_000 and text.index("quokka") > 48_000
    out = ok("search_knowledge", {"query": "quokka"}, _knowledge_ctx(text))
    assert "The quokka clause: free quokka returns." in out
    assert len(out) <= TOOL_RESULT_MAX_CHARS


def test_search_knowledge_stem_never_reaches_the_other_shops_knowledge():
    shop_b = {**SHOP_B, "knowledge": "ექსკლუზიური გარანტიის პირობები: 99 წელი."}
    assert "99 წელი" in ok("search_knowledge", {"query": "გარანტია"}, ToolContext(shop=shop_b, products=[]))
    shop_a = {**SHOP_A, "knowledge": "მიწოდება თბილისში 5 ლარი."}
    out = ok("search_knowledge", {"query": "გარანტია"}, ToolContext(shop=shop_a, products=[]))
    assert out == "No matching information in the shop knowledge." and "99" not in out


# --- order_link / request_human ------------------------------------------------------------
def test_order_link_equals_prompt_order_link():
    assert execute("order_link", {}, ctx_a()) == ToolOutcome("Order link: " + prompt.order_link_for(SHOP_A))
    assert f"/panel/order.html?shop={SHOP_A_ID}" in ok("order_link", {}, ctx_a())
    assert prompt.order_link_for(SHOP_B) in ok("order_link", {}, ctx_b())


def test_request_human_is_handled_by_the_system():
    for args in ({"reason": "complaint"}, {}, None, "junk"):
        assert execute(HUMAN_TOOL, args, ctx_a()) == ToolOutcome("Error: handled by the system.", True)


def test_unknown_tool():
    for name in ("delete_everything", "", None, 5, "SEARCH_PRODUCTS"):
        assert execute(name, {"query": "x"}, ctx_a()) == ToolOutcome("Error: unknown tool.", True)


# --- invalid arguments ---------------------------------------------------------------------
@pytest.mark.parametrize("name", ["search_products", "search_knowledge"])
@pytest.mark.parametrize("args", [
    None, "red shirt", ["query"], 5, {}, {"query": None}, {"query": 5}, {"query": ["x"]},
    {"query": ""}, {"query": "   \n\t"}, {"query": "x" * 201}, {"query": " " + "x" * 201},
])
def test_invalid_arguments(name, args):
    assert execute(name, args, ctx_a()) == ToolOutcome(f"Error: invalid arguments for {name}.", True)


@pytest.mark.parametrize("args", [None, [], "x", 0])
def test_order_link_invalid_arguments(args):
    assert execute("order_link", args, ctx_a()) == ToolOutcome("Error: invalid arguments for order_link.", True)


def test_query_length_boundaries_are_valid():
    ok("search_products", {"query": "x"}, ctx_a())
    ok("search_products", {"query": "x" * 200}, ctx_a())
    ok("search_knowledge", {"query": "  " + "x" * 200 + "  "}, ctx_a())  # strip first, then the 200 limit


def test_execute_never_raises_on_broken_context():
    broken = ToolContext(shop={"id": SHOP_A_ID}, products=[{"name": None}, {"name": 5, "description": object()}])
    for name, args in (("search_products", {"query": "item"}), ("search_knowledge", {"query": "item"}),
                       ("order_link", {})):
        out = execute(name, args, broken)
        assert isinstance(out, ToolOutcome) and isinstance(out.content, str)
    # a non-dict shop makes the executors fail internally: still an error outcome, no exception
    out = execute("order_link", {}, ToolContext(shop=None, products=[]))
    assert out == ToolOutcome("Error: tool failed.", True)
