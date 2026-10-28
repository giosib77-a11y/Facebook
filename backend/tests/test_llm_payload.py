"""S14-4: Claude / OpenAI request payloads (pure, offline)."""
import base64
import logging

from app.services import llm
from app.services.prompt import Prompt

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
    assert req["cache_control"] == {"type": "ephemeral"}


def test_claude_fixed_params_and_no_sampling():
    req = llm.build_claude_request(_prompt(), "m")
    assert req["max_tokens"] == 800
    assert req["thinking"] == {"type": "disabled"}
    for forbidden in ("temperature", "top_p", "top_k"):
        assert forbidden not in req


def test_claude_messages_history_and_final_blocks():
    req = llm.build_claude_request(_prompt(), "m")
    msgs = req["messages"]
    assert msgs[0] == {"role": "user", "content": "hi"}
    assert msgs[1] == {"role": "assistant", "content": "hello"}
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
        {"role": "user", "content": "a"},
        {"role": "user", "content": [{"type": "text", "text": "b"}]},
    ]


def test_claude_empty_history():
    msgs = llm.build_claude_request(_prompt(history=[]), "m")["messages"]
    assert len(msgs) == 1 and msgs[0]["role"] == "user"


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
