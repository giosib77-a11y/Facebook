"""S18-2: llm.complete(images=) - Claude image block / OpenAI input_image (detail low), the shared image
filter, byte-identical requests without images. Fake SDK clients only - no network, no .env."""
import base64
import copy
import logging
import time
from types import SimpleNamespace

import pytest

from app.services import llm

SHOP = "11111111-aaaa-bbbb-cccc-222222222222"
SYSTEM = "You are a describer."
TEXT = "Photo to describe:"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(40))
JPG = b"\xff\xd8\xff\xe0" + bytes(range(30))
PNG_B64 = base64.b64encode(PNG).decode("ascii")
JPG_B64 = base64.b64encode(JPG).decode("ascii")


def _claude_response(text="EN: a red shirt\nKA: მაისური, წითელი"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=11, output_tokens=7,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )


def _openai_response(text="EN: a red shirt\nKA: მაისური, წითელი"):
    return SimpleNamespace(
        output_text=text, output=[],
        usage=SimpleNamespace(input_tokens=100, output_tokens=9,
                              input_tokens_details=SimpleNamespace(cached_tokens=0)),
    )


class Env:
    def __init__(self, monkeypatch, provider):
        self.requests = []
        update = {"llm_provider": provider}
        if provider == "openai":
            update["openai_api_key"] = "test-openai-key-not-real"
        self.settings = llm.get_settings().model_copy(update=update)
        monkeypatch.setattr(llm, "get_settings", lambda: self.settings)
        make = _claude_response if provider == "claude" else _openai_response

        def create(**kwargs):
            self.requests.append(copy.deepcopy(kwargs))
            return make()

        client = SimpleNamespace(messages=SimpleNamespace(create=create),
                                 responses=SimpleNamespace(create=create))
        monkeypatch.setattr(llm, "_anthropic_client", lambda s: client)
        monkeypatch.setattr(llm, "_openai_client", lambda s: client)


@pytest.fixture(params=["claude", "openai"])
def env(request, monkeypatch):
    return Env(monkeypatch, request.param)


def _content(request):
    if "messages" in request:
        return request["messages"][0]["content"]
    return request["input"][1]["content"]


# ---------------------------------------------------------------------------
# request shapes
# ---------------------------------------------------------------------------
def test_claude_request_shape_with_one_png():
    req = llm.build_claude_complete_request(SYSTEM, TEXT, "m", 300, [(PNG, "image/png")])
    assert req == {
        "model": "m",
        "max_tokens": 300,
        "thinking": {"type": "disabled"},
        "system": [{"type": "text", "text": SYSTEM}],
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG_B64}},
            {"type": "text", "text": TEXT},
        ]}],
    }
    assert "cache_control" not in repr(req) and "tools" not in req


def test_claude_images_come_before_the_text_in_the_given_order():
    req = llm.build_claude_complete_request(SYSTEM, TEXT, "m", 300, [(PNG, "image/png"), (JPG, " IMAGE/JPEG ")])
    content = req["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "image", "text"]
    assert content[0]["source"]["data"] == PNG_B64
    assert content[1]["source"] == {"type": "base64", "media_type": "image/jpeg", "data": JPG_B64}  # mime normalised


def test_openai_request_shape_with_one_png():
    req = llm.build_openai_complete_request(SYSTEM, TEXT, "m", 300, [(PNG, "image/png")])
    assert req == {
        "model": "m",
        "input": [
            {"role": "developer", "content": [{"type": "input_text", "text": SYSTEM}]},
            {"role": "user", "content": [
                {"type": "input_image", "image_url": f"data:image/png;base64,{PNG_B64}", "detail": "low"},
                {"type": "input_text", "text": TEXT},
            ]},
        ],
        "max_output_tokens": 300,
        "store": False,
    }
    assert req["store"] is False and "prompt_cache_key" not in req and "tools" not in req


def test_builders_match_the_sdk_param_shapes():
    """The block shapes are the ones the installed SDKs declare (type / source / detail keys)."""
    from anthropic.types import Base64ImageSourceParam, ImageBlockParam
    from openai.types.responses import ResponseInputImageParam

    block = llm.build_claude_complete_request(SYSTEM, TEXT, "m", 1, [(PNG, "image/png")])["messages"][0]["content"][0]
    assert set(block) <= set(ImageBlockParam.__annotations__)
    assert set(block["source"]) == set(Base64ImageSourceParam.__annotations__)
    part = llm.build_openai_complete_request(SYSTEM, TEXT, "m", 1, [(PNG, "image/png")])["input"][1]["content"][0]
    assert set(part) <= set(ResponseInputImageParam.__annotations__)


# ---------------------------------------------------------------------------
# no images -> the old request, byte for byte
# ---------------------------------------------------------------------------
def test_legacy_requests_are_unchanged_literals():
    assert llm.build_claude_complete_request(SYSTEM, TEXT, "m", 50) == {
        "model": "m", "max_tokens": 50, "thinking": {"type": "disabled"},
        "system": [{"type": "text", "text": SYSTEM}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": TEXT}]}],
    }
    assert llm.build_openai_complete_request(SYSTEM, TEXT, "m", 50) == {
        "model": "m",
        "input": [
            {"role": "developer", "content": [{"type": "input_text", "text": SYSTEM}]},
            {"role": "user", "content": [{"type": "input_text", "text": TEXT}]},
        ],
        "max_output_tokens": 50, "store": False,
    }


@pytest.mark.parametrize("images", [None, [], [(PNG, "image/bmp")], [(b"x" * (llm.MAX_IMAGE_BYTES + 1), "image/png")],
                                    [(b"", "image/png")], [("not bytes", "image/png")], [(PNG, None)]])
def test_unusable_images_give_the_same_request_as_no_images(images):
    claude = llm.build_claude_complete_request(SYSTEM, TEXT, "m", 50, images)
    assert claude == llm.build_claude_complete_request(SYSTEM, TEXT, "m", 50)
    openai_req = llm.build_openai_complete_request(SYSTEM, TEXT, "m", 50, images)
    assert openai_req == llm.build_openai_complete_request(SYSTEM, TEXT, "m", 50)


def test_complete_without_usable_images_sends_the_same_request(env):
    llm.complete(SYSTEM, TEXT, SHOP, max_tokens=50)
    for images in (None, [], [(PNG, "image/bmp")], [(b"x" * (llm.MAX_IMAGE_BYTES + 1), "image/png")]):
        llm.complete(SYSTEM, TEXT, SHOP, max_tokens=50, images=images)
    assert len(env.requests) == 5
    assert all(r == env.requests[0] for r in env.requests)


def test_skipped_images_log_the_same_warnings_as_generate(caplog):
    with caplog.at_level(logging.WARNING, logger="app"):
        llm.build_claude_complete_request(SYSTEM, TEXT, "m", 50, [(PNG, "image/bmp"), (PNG, "image/png")])
        llm.build_claude_complete_request(SYSTEM, TEXT, "m", 50, [(b"x" * (llm.MAX_IMAGE_BYTES + 1), "image/png")])
    messages = [r.getMessage() for r in caplog.records]
    assert "LLM image skipped: unsupported mime type 'image/bmp'" in messages
    assert any(m.startswith("LLM image skipped: too large (") for m in messages)


def test_only_the_valid_images_are_sent():
    req = llm.build_claude_complete_request(SYSTEM, TEXT, "m", 50, [(PNG, "image/bmp"), (JPG, "image/jpeg")])
    content = req["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "text"]
    assert content[0]["source"]["data"] == JPG_B64


def test_generate_image_filter_is_unchanged():
    from app.services.prompt import Prompt

    final = [
        {"type": "image", "data": PNG, "mime": "image/bmp"},
        {"type": "image", "data": b"", "mime": "image/png"},
        {"type": "image", "data": JPG, "mime": "image/jpeg"},
        {"type": "text", "text": "hi"},
    ]
    items = llm._usable_images_and_texts(final)
    assert items == [("image", "image/jpeg", JPG_B64), ("text", "hi")]
    assert llm._usable_images_and_texts([{"type": "image", "data": PNG, "mime": "image/bmp"}]) == [
        ("text", llm._EMPTY_FINAL_TEXT)]
    prompt = Prompt(layer1="L1", layer2="L2", history=[], final=final)
    assert llm.build_claude_request(prompt, "m")["messages"][-1]["content"][0]["source"]["data"] == JPG_B64


# ---------------------------------------------------------------------------
# complete(images=) end to end through a fake client
# ---------------------------------------------------------------------------
def test_complete_with_images_makes_one_call_and_returns_the_text(env):
    result = llm.complete(SYSTEM, TEXT, SHOP, max_tokens=300, images=[(PNG, "image/png")])
    assert len(env.requests) == 1
    req = env.requests[0]
    content = _content(req)
    assert len(content) == 2 and content[-1]["text"] == TEXT
    if env.settings.llm_provider == "claude":
        assert content[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                          "data": PNG_B64}}
        assert req["max_tokens"] == 300
        assert result.provider == "claude" and result.usage.input_tokens == 11
    else:
        assert content[0] == {"type": "input_image", "image_url": f"data:image/png;base64,{PNG_B64}",
                              "detail": "low"}
        assert req["store"] is False and "prompt_cache_key" not in req and req["max_output_tokens"] == 300
        assert result.provider == "openai" and result.usage.output_tokens == 9
    assert result.text == "EN: a red shirt\nKA: მაისური, წითელი"


def test_complete_with_images_and_provider_override_and_deadline(monkeypatch):
    env = Env(monkeypatch, "claude")
    env.settings = env.settings.model_copy(update={"openai_api_key": "test-openai-key-not-real"})
    result = llm.complete(SYSTEM, TEXT, SHOP, max_tokens=300, provider="openai", images=[(PNG, "image/png")],
                          deadline=time.monotonic() + 30)
    assert result.provider == "openai"
    assert _content(env.requests[0])[0]["type"] == "input_image"
