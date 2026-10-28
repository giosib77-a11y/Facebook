"""S14-4: Claude / OpenAI request payloads (pure, offline)."""
import base64
import logging

import pytest

from app.services import llm
from app.services.prompt import Prompt, build_prompt

L1 = "LAYER ONE rules"
L2 = "LAYER TWO shop block"
PNG = b"\x89PNG-bytes"


def _prompt(history=None, final=None):
    return Prompt(
        layer1=L1,
        layer2=L2,
        history=history if history is not None else [
            {"role": "user", "text": "hi"},
            {"role": "assistant", "text": "hello"},
        ],
        final=final if final is not None else [
            {"type": "text", "text": "photo:"},
            {"type": "image", "data": PNG, "mime": "image/png"},
            {"type": "text", "text": "how much?"},
        ],
    )


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------
def test_claude_system_blocks_and_cache_control():
    req = llm.build_claude_request(_prompt(), "claude-x")
    assert req["model"] == "claude-x"
    assert req["system"] == [
        {"type": "text", "text": L1, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        {"type": "text", "text": L2, "cache_control": {"type": "ephemeral", "ttl": "5m"}},
    ]
    assert "cache_control" not in req  # no automatic caching: it would pin the breakpoint to the final turn


def _breakpoints(req):
    """Every cache_control in the request, in prompt order: [(where, cache_control)]."""
    out = [(f"system[{i}]", b["cache_control"]) for i, b in enumerate(req["system"]) if "cache_control" in b]
    for mi, m in enumerate(req["messages"]):
        content = m["content"]
        assert isinstance(content, list), "Claude history messages must be block lists"
        out.extend((f"messages[{mi}][{bi}]", b["cache_control"])
                   for bi, b in enumerate(content) if "cache_control" in b)
    return out


def _strip_cc(messages):
    return [{**m, "content": [{k: v for k, v in b.items() if k != "cache_control"} for b in m["content"]]}
            for m in messages]


def test_claude_breakpoint_only_on_last_history_block():
    req = llm.build_claude_request(_prompt(), "m")
    msgs = req["messages"]
    assert msgs[0] == {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    assert msgs[1] == {"role": "assistant", "content": [
        {"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}}]}
    assert all("cache_control" not in b for b in msgs[-1]["content"])  # final turn is never a breakpoint
    assert "cache_control" not in req
    assert [w for w, _ in _breakpoints(req)] == ["system[0]", "system[1]", "messages[1][0]"]


def test_claude_breakpoint_count_and_ttl_order():
    req = llm.build_claude_request(_prompt(), "m")
    bps = [cc for _, cc in _breakpoints(req)]
    assert len(bps) == 3 <= 4
    # a longer TTL must precede a shorter one; a missing ttl means the 5m default
    assert [cc.get("ttl", "5m") for cc in bps] == ["1h", "5m", "5m"]


def test_claude_empty_history_has_no_l3_breakpoint():
    req = llm.build_claude_request(_prompt(history=[]), "m")
    assert [w for w, _ in _breakpoints(req)] == ["system[0]", "system[1]"]
    assert "cache_control" not in req


def test_claude_cache_control_is_not_shared_between_requests():
    p = _prompt()
    a = llm.build_claude_request(p, "m")
    b = llm.build_claude_request(p, "m")
    a["messages"][1]["content"][0]["cache_control"]["ttl"] = "mutated"
    assert b["messages"][1]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_claude_fixed_params_and_no_sampling():
    req = llm.build_claude_request(_prompt(), "m")
    assert req["max_tokens"] == 800
    assert req["thinking"] == {"type": "disabled"}
    for forbidden in ("temperature", "top_p", "top_k"):
        assert forbidden not in req


def test_claude_messages_history_and_final_blocks():
    req = llm.build_claude_request(_prompt(), "m")
    msgs = req["messages"]
    assert msgs[0]["content"] == [{"type": "text", "text": "hi"}]
    assert msgs[1]["role"] == "assistant" and msgs[1]["content"][0]["text"] == "hello"
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == [
        {"type": "text", "text": "photo:"},
        {"type": "image", "source": {
            "type": "base64", "media_type": "image/png", "data": base64.b64encode(PNG).decode(),
        }},
        {"type": "text", "text": "how much?"},
    ]
    # never an assistant prefill: the last message is the user's
    assert msgs[-1]["role"] != "assistant"


def test_claude_history_ending_with_user_keeps_both_in_order():
    p = _prompt(history=[{"role": "user", "text": "a"}], final=[{"type": "text", "text": "b"}])
    msgs = llm.build_claude_request(p, "m")["messages"]
    assert msgs == [
        {"role": "user", "content": [{"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}}]},
        {"role": "user", "content": [{"type": "text", "text": "b"}]},
    ]


def test_claude_empty_history():
    msgs = llm.build_claude_request(_prompt(history=[]), "m")["messages"]
    assert len(msgs) == 1 and msgs[0]["role"] == "user"


# ---------------------------------------------------------------------------
# Cross-turn: the cached prefix of turn N must be a byte-exact prefix of turn N+1 (SF-1)
# ---------------------------------------------------------------------------
SHOP = {"id": "s1", "name": "Tbilisi Style", "description": "Clothes", "currency": "GEL", "knowledge": ""}


def _catalogue(n):
    return [{"id": f"{i:04d}", "name": f"Item {i}", "price": 10 + i, "quantity": 1 + i % 3,
             "sku": f"S{i}", "description": f"desc {i}"} for i in range(n)]


def _webhook_history(stored, user_text, reply):
    """What the webhook persists after a turn: the raw customer text (never the final-turn blocks)."""
    return stored + [{"role": "user", "content": user_text}, {"role": "bot", "content": reply}]


@pytest.mark.parametrize("n_products", [5, 40])
def test_cached_prefix_survives_into_next_turn(n_products):
    products = _catalogue(n_products)
    stored = [{"role": "user", "content": "hi"}, {"role": "bot", "content": "hello!"}]

    # turn N: photo + (for 40 products) the "Relevant products" block in the final turn
    p_n = build_prompt(SHOP, products, "Item 25 please?", stored,
                       images=[(PNG, "image/jpeg")], product_refs=[("Item 25", (PNG, "image/jpeg"))])
    req_n = llm.build_claude_request(p_n, "m")
    if n_products > 30:
        assert "Relevant products for this message" in req_n["messages"][-1]["content"][0]["text"]

    # turn N+1: history = N's history + the raw text the webhook stored + the assistant reply
    stored_n1 = _webhook_history(stored, "Item 25 please?", "13 GEL, size M is available")
    p_n1 = build_prompt(SHOP, products, "and Item 3?", stored_n1)
    req_n1 = llm.build_claude_request(p_n1, "m")

    # automatic (top-level) caching would put the breakpoint at the end of the variable final turn
    assert "cache_control" not in req_n and "cache_control" not in req_n1

    n_hist = len(p_n.history)
    assert n_hist == 2
    assert len(p_n1.history) == n_hist + 2
    assert _strip_cc(req_n1["messages"][:n_hist]) == _strip_cc(req_n["messages"][:n_hist])
    assert req_n1["system"] == req_n["system"]

    # the breakpoint of N+1 sits at the end of its history, which holds everything N cached
    assert [w for w, _ in _breakpoints(req_n)] == ["system[0]", "system[1]", f"messages[{n_hist - 1}][0]"]
    assert [w for w, _ in _breakpoints(req_n1)] == ["system[0]", "system[1]", f"messages[{n_hist + 1}][0]"]


def test_no_breakpoint_on_variable_final_turn_without_history():
    """The final turn (images, 'Relevant products') is not re-sent verbatim on the next turn, so with
    no history only the two system breakpoints exist."""
    products = _catalogue(40)
    req = llm.build_claude_request(
        build_prompt(SHOP, products, "Item 25?", [], images=[(PNG, "image/jpeg")]), "m")
    assert "cache_control" not in req
    assert [w for w, _ in _breakpoints(req)] == ["system[0]", "system[1]"]


def test_claude_skips_bad_mime_and_oversized_images(caplog):
    caplog.set_level(logging.WARNING)
    big = b"x" * (llm.MAX_IMAGE_BYTES + 1)
    p = _prompt(final=[
        {"type": "image", "data": PNG, "mime": "image/svg+xml"},
        {"type": "image", "data": big, "mime": "image/jpeg"},
        {"type": "image", "data": PNG, "mime": "IMAGE/JPEG"},  # case-insensitive, kept
        {"type": "text", "text": "q"},
    ])
    content = llm.build_claude_request(p, "m")["messages"][-1]["content"]
    assert [b["type"] for b in content] == ["image", "text"]
    assert content[0]["source"]["media_type"] == "image/jpeg"
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2


def test_image_at_exact_limit_is_kept():
    p = _prompt(final=[{"type": "image", "data": b"x" * llm.MAX_IMAGE_BYTES, "mime": "image/webp"},
                       {"type": "text", "text": "q"}])
    content = llm.build_claude_request(p, "m")["messages"][-1]["content"]
    assert [b["type"] for b in content] == ["image", "text"]


def test_skipping_all_images_keeps_the_text_part():
    p = _prompt(final=[{"type": "image", "data": PNG, "mime": "image/bmp"},
                       {"type": "text", "text": "what is this?"}])
    content = llm.build_claude_request(p, "m")["messages"][-1]["content"]
    assert content == [{"type": "text", "text": "what is this?"}]


def test_final_never_empty_even_if_only_a_bad_image():
    p = _prompt(final=[{"type": "image", "data": PNG, "mime": "image/bmp"}])
    content = llm.build_claude_request(p, "m")["messages"][-1]["content"]
    assert len(content) == 1 and content[0]["type"] == "text" and content[0]["text"]


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------
def test_openai_developer_message_and_fixed_params():
    req = llm.build_openai_request(_prompt(), "gpt-x", "shop-1")
    assert req["model"] == "gpt-x"
    assert req["input"][0] == {"role": "developer", "content": [
        {"type": "input_text", "text": L1},
        {"type": "input_text", "text": L2},
    ]}
    assert req["max_output_tokens"] == 800
    assert req["prompt_cache_key"] == "shop:shop-1"
    assert req["store"] is False
    for forbidden in ("temperature", "top_p", "top_k", "reasoning", "max_tokens"):
        assert forbidden not in req


def test_openai_history_and_final_with_data_url():
    items = llm.build_openai_request(_prompt(), "m", "s")["input"]
    assert items[1] == {"role": "user", "content": "hi"}
    assert items[2] == {"role": "assistant", "content": "hello"}
    assert items[-1] == {"role": "user", "content": [
        {"type": "input_text", "text": "photo:"},
        {"type": "input_image",
         "image_url": "data:image/png;base64," + base64.b64encode(PNG).decode(),
         "detail": "auto"},
        {"type": "input_text", "text": "how much?"},
    ]}


def test_openai_history_ending_with_user_keeps_both_in_order():
    p = _prompt(history=[{"role": "user", "text": "a"}], final=[{"type": "text", "text": "b"}])
    items = llm.build_openai_request(p, "m", "s")["input"]
    assert [i["role"] for i in items] == ["developer", "user", "user"]
    assert items[1]["content"] == "a"
    assert items[2]["content"] == [{"type": "input_text", "text": "b"}]


def test_openai_skips_bad_mime_and_oversized_images():
    big = b"x" * (llm.MAX_IMAGE_BYTES + 1)
    p = _prompt(final=[
        {"type": "image", "data": PNG, "mime": "application/pdf"},
        {"type": "image", "data": big, "mime": "image/png"},
        {"type": "text", "text": "q"},
    ])
    content = llm.build_openai_request(p, "m", "s")["input"][-1]["content"]
    assert content == [{"type": "input_text", "text": "q"}]


def test_oversize_warning_has_no_image_data_or_url(caplog):
    caplog.set_level(logging.WARNING)
    big = b"SECRETBYTES" * (llm.MAX_IMAGE_BYTES // 8)
    llm.build_claude_request(_prompt(final=[{"type": "image", "data": big, "mime": "image/png"}]), "m")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "SECRETBYTES" not in text and "http" not in text
