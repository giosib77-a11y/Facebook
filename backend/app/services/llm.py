"""LLM calls for the bot: Claude (default) / OpenAI — request building, bounded retry, usage.

Takes the provider-agnostic Prompt from services/prompt.py and returns plain text + normalized
token usage. The provider is chosen by Settings.llm_provider
(or by generate(provider=...) — Stage 15 comparison script).

Rules enforced here:
  - SDK retries are OFF (max_retries=0): both SDKs honour `retry-after` with no practical cap,
    so a single 429 could block a webhook worker for minutes. generate() makes at most ONE
    retry itself, inside LLM_TOTAL_BUDGET_SECONDS.
  - No sampling parameters (temperature/top_p/top_k), no assistant prefill, no reasoning
    parameters: provider defaults only.
  - Claude cache breakpoints (max 3 of 4, longer TTL first): L1 system (1h) -> L2 system (5m) ->
    the last history block (5m). The final user turn is never a breakpoint: it is rebuilt per message
    (relevant-product subset, photos) and the webhook stores only the raw customer text in history,
    so a breakpoint there could never be read back on the next turn.
  - Provider SDKs are imported lazily (inside functions) and the clients are built only by the two
    factories below. Tests replace the factories (conftest blocks the real ones).
  - Stage 16 (all optional, the default request is unchanged): provider-neutral tool specs and the
    in-turn transcript (`steps`) are passed in by the caller (this module never imports tools.py);
    tools carry NO cache_control (they precede the system prompt, so the L1 1h breakpoint covers
    tools + L1); `deadline` (absolute time.monotonic() value) bounds a whole bot turn.
"""
import base64
import json
import logging
import time
from dataclasses import dataclass, field

from app.config import get_settings
from app.core.supabase_client import get_service_client

logger = logging.getLogger("app")

PROVIDERS = ("claude", "openai")

MAX_OUTPUT_TOKENS = 800
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})

LLM_RETRY_DELAY = 1.5  # seconds before the single retry (retry-after is ignored)
LLM_TOTAL_BUDGET_SECONDS = 45.0  # whole generate() call, retry included
LLM_MIN_ATTEMPT_SECONDS = 3.0  # with a deadline: no attempt (or retry) that has less time than this

_EMPTY_FINAL_TEXT = "(The customer sent an empty message.)"


@dataclass
class Usage:
    input_tokens: int = 0  # uncached input
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict | None  # None: the model's arguments were not a valid JSON object
    raw_arguments: str  # original JSON string (OpenAI needs it back verbatim in the next request)


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    usage: Usage
    tool_calls: list[ToolCall] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Client factories — the only places where a provider SDK client is constructed.
# ---------------------------------------------------------------------------
def _anthropic_client(s):
    import anthropic

    return anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=s.llm_timeout_seconds, max_retries=0)


def _openai_client(s):
    import openai

    return openai.OpenAI(api_key=s.openai_api_key, timeout=s.llm_timeout_seconds, max_retries=0)


# ---------------------------------------------------------------------------
# Request building (pure)
# ---------------------------------------------------------------------------
def usable_image(data, mime) -> tuple[str, str] | None:
    """One image -> (mime, base64) or None when it is skipped: not bytes / empty (silently),
    unsupported mime or over MAX_IMAGE_BYTES (WARNING without URL/PSID). The single image filter of
    generate() and complete()."""
    mime = mime.strip().lower() if isinstance(mime, str) else ""
    if not data or not isinstance(data, (bytes, bytearray)):
        return None
    if mime not in ALLOWED_IMAGE_MIMES:
        logger.warning("LLM image skipped: unsupported mime type %r", mime[:40])
        return None
    if len(data) > MAX_IMAGE_BYTES:
        logger.warning("LLM image skipped: too large (%d bytes)", len(data))
        return None
    return mime, base64.b64encode(bytes(data)).decode("ascii")


def _usable_images_and_texts(final: list[dict]):
    """Final-turn parts -> [("text", str) | ("image", mime, b64)], skipping unsupported/oversized
    images (WARNING without URL/PSID). Never returns an empty list."""
    out: list = []
    for part in final or []:
        if part.get("type") == "text":
            text = part.get("text")
            if isinstance(text, str) and text:
                out.append(("text", text))
        elif part.get("type") == "image":
            image = usable_image(part.get("data"), part.get("mime"))
            if image is not None:
                out.append(("image", image[0], image[1]))
    if not out:
        out.append(("text", _EMPTY_FINAL_TEXT))
    return out


def build_claude_request(prompt, model: str, *, tools=None, steps=None, force_text: bool = False) -> dict:
    final_blocks = []
    for item in _usable_images_and_texts(prompt.final):
        if item[0] == "text":
            final_blocks.append({"type": "text", "text": item[1]})
        else:
            final_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": item[1], "data": item[2]},
            })
    # History as block lists so the last block can carry the L3 breakpoint. No top-level
    # (automatic) cache_control: it would put the breakpoint at the end of the final turn, whose
    # content (product subset, photos) never reappears in that form in the next request's history.
    messages = [{"role": t["role"], "content": [{"type": "text", "text": t["text"]}]} for t in prompt.history]
    if messages:
        messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}  # 5m, after the 1h -> 5m system
    messages.append({"role": "user", "content": final_blocks})
    # In-turn transcript after the final user turn: never a breakpoint.
    for step in steps or []:
        assistant = []
        # Whitespace-only text (e.g. "\n\n" before a tool_use) is a 400 on Anthropic -> skip it;
        # real text is sent unchanged (no strip) so the prefix stays stable.
        if (step.get("text") or "").strip():
            assistant.append({"type": "text", "text": step["text"]})
        for call in step.get("calls") or []:
            assistant.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments or {}})
        messages.append({"role": "assistant", "content": assistant})
        results = []
        for r in step.get("results") or []:
            block = {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"]}
            if r.get("is_error"):
                block["is_error"] = True
            results.append(block)
        messages.append({"role": "user", "content": results})
    request = {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "thinking": {"type": "disabled"},
        "system": [
            {"type": "text", "text": prompt.layer1, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": prompt.layer2, "cache_control": {"type": "ephemeral", "ttl": "5m"}},
        ],
        "messages": messages,
    }
    if tools:
        # No cache_control on tools: they come before `system` in the cached prefix, so the L1 1h
        # breakpoint already covers tools + L1.
        request["tools"] = [
            {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools
        ]
    if force_text:
        request["tool_choice"] = {"type": "none"}
    return request


def build_openai_request(prompt, model: str, shop_id, *, tools=None, steps=None, force_text: bool = False) -> dict:
    final_content = []
    for item in _usable_images_and_texts(prompt.final):
        if item[0] == "text":
            final_content.append({"type": "input_text", "text": item[1]})
        else:
            final_content.append({
                "type": "input_image",
                "image_url": f"data:{item[1]};base64,{item[2]}",
                "detail": "auto",
            })
    items = [{
        "role": "developer",
        "content": [
            {"type": "input_text", "text": prompt.layer1},
            {"type": "input_text", "text": prompt.layer2},
        ],
    }]
    items.extend({"role": t["role"], "content": t["text"]} for t in prompt.history)
    items.append({"role": "user", "content": final_content})
    # store=False -> the whole in-turn transcript is re-sent on every call (no previous_response_id);
    # the original `arguments` string goes back untouched. Reasoning items are not re-sent.
    for step in steps or []:
        if (step.get("text") or "").strip():  # same rule as Claude: whitespace-only text is skipped
            items.append({"role": "assistant", "content": step["text"]})
        for call in step.get("calls") or []:
            items.append({
                "type": "function_call", "call_id": call.id, "name": call.name, "arguments": call.raw_arguments,
            })
        for r in step.get("results") or []:
            items.append({"type": "function_call_output", "call_id": r["id"], "output": r["content"]})
    request = {
        "model": model,
        "input": items,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "prompt_cache_key": f"shop:{shop_id}",
        "store": False,
    }
    if tools:
        request["tools"] = [
            {"type": "function", "name": t["name"], "description": t["description"],
             "parameters": t["parameters"], "strict": True}
            for t in tools
        ]
    if force_text:
        request["tool_choice"] = "none"
    return request


def _usable_images(images) -> list[tuple[str, str]]:
    """complete(images=[(bytes, mime), ...]) -> [(mime, b64)] through the same filter as generate()."""
    out = []
    for item in images or []:
        try:
            data, mime = item
        except (TypeError, ValueError):
            continue
        image = usable_image(data, mime)
        if image is not None:
            out.append(image)
    return out


def build_claude_complete_request(system: str, text: str, model: str, max_tokens: int, images=None) -> dict:
    """Plain one-shot call (summary, FAQ, photo description): no tools, no cache_control.
    images=[(bytes, mime)] (Stage 18): image blocks before the text; None / nothing usable -> text only."""
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}
        for mime, b64 in _usable_images(images)
    ]
    content.append({"type": "text", "text": text})
    return {
        "model": model,
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
        "system": [{"type": "text", "text": system}],
        "messages": [{"role": "user", "content": content}],
    }


def build_openai_complete_request(system: str, text: str, model: str, max_tokens: int, images=None) -> dict:
    # detail "low" (~85 tokens): enough for item type / colours, and identical on both sides of a match.
    content = [
        {"type": "input_image", "image_url": f"data:{mime};base64,{b64}", "detail": "low"}
        for mime, b64 in _usable_images(images)
    ]
    content.append({"type": "input_text", "text": text})
    return {
        "model": model,
        "input": [
            {"role": "developer", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": content},
        ],
        "max_output_tokens": max_tokens,
        "store": False,
    }


# ---------------------------------------------------------------------------
# Usage normalization
# ---------------------------------------------------------------------------
def _tok(obj, name: str) -> int:
    """Token counter attribute -> int >= 0 (None / missing / non-numeric -> 0)."""
    value = getattr(obj, name, None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _claude_usage(usage) -> Usage:
    return Usage(
        input_tokens=_tok(usage, "input_tokens"),
        output_tokens=_tok(usage, "output_tokens"),
        cache_read_tokens=_tok(usage, "cache_read_input_tokens"),
        cache_write_tokens=_tok(usage, "cache_creation_input_tokens"),
    )


def _openai_usage(usage) -> Usage:
    # Responses API: input_tokens is the TOTAL (cached + cache-write + uncached); input_tokens_details
    # is a breakdown. Uncached = total - cached - cache_write (same semantics as Claude's input_tokens).
    # Evidence: openai SDK 3.40 usage API docs ("input_tokens ... including cached and cache-write
    # tokens"; "input_uncached_tokens ... excluding cache-write tokens"). ASSUMPTION for the
    # Responses `usage` object itself — verify against a real response in Stage 15.
    details = getattr(usage, "input_tokens_details", None)
    cached = _tok(details, "cached_tokens")
    written = _tok(details, "cache_write_tokens")
    return Usage(
        input_tokens=max(0, _tok(usage, "input_tokens") - cached - written),
        output_tokens=_tok(usage, "output_tokens"),
        cache_read_tokens=cached,
        cache_write_tokens=written,
    )


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------
def _raw_json(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"


def _send_claude(s, request: dict, shop_id, timeout: float | None) -> LLMResult:
    # `timeout` (per-request, seconds) only when a turn deadline is active; otherwise the client default.
    extra = {} if timeout is None else {"timeout": timeout}
    response = _anthropic_client(s).messages.create(**request, **extra)
    text = "".join(
        (getattr(b, "text", "") or "")
        for b in (getattr(response, "content", None) or [])
        if getattr(b, "type", None) == "text"
    )
    if getattr(response, "stop_reason", None) == "refusal":
        logger.warning("LLM refused to answer (shop=%s)", shop_id)
        return LLMResult("", "claude", s.llm_model, _claude_usage(getattr(response, "usage", None)))
    tool_calls = []
    for b in getattr(response, "content", None) or []:
        if getattr(b, "type", None) != "tool_use":
            continue
        args = getattr(b, "input", None)
        tool_calls.append(ToolCall(
            id=str(getattr(b, "id", "") or ""),
            name=str(getattr(b, "name", "") or ""),
            arguments=args if isinstance(args, dict) else None,
            raw_arguments=_raw_json(args),
        ))
    return LLMResult(text, "claude", s.llm_model, _claude_usage(getattr(response, "usage", None)), tool_calls)


def _send_openai(s, request: dict, shop_id, timeout: float | None) -> LLMResult:
    extra = {} if timeout is None else {"timeout": timeout}
    response = _openai_client(s).responses.create(**request, **extra)
    text = getattr(response, "output_text", None) or ""
    tool_calls = []
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "function_call":
            continue
        raw = getattr(item, "arguments", None)
        raw = raw if isinstance(raw, str) else ""
        try:
            args = json.loads(raw)
        except ValueError:
            args = None
        tool_calls.append(ToolCall(
            id=str(getattr(item, "call_id", "") or ""),
            name=str(getattr(item, "name", "") or ""),
            arguments=args if isinstance(args, dict) else None,
            raw_arguments=raw,
        ))
    return LLMResult(text, "openai", s.llm_model, _openai_usage(getattr(response, "usage", None)), tool_calls)


def _is_transient(exc: BaseException) -> bool:
    """Connection/timeout, 429, 5xx (incl. Anthropic 529) of either SDK. Other 4xx are not retried."""
    import anthropic
    import openai

    if isinstance(exc, (
        anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError,
        openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError,
    )):
        return True
    if isinstance(exc, (anthropic.APIStatusError, openai.APIStatusError)):
        return exc.status_code >= 500
    return False


def _settings_for(provider: str | None):
    s = get_settings()
    if provider is not None:
        if provider not in PROVIDERS:
            raise ValueError(f"unknown LLM provider: {provider!r}")
        s = s.model_copy(update={"llm_provider": provider})
    if not s.llm_ready:
        raise RuntimeError(f"LLM key not configured: {s.llm_key_env_name}")
    return s


def _with_retry(s, send, shop_id, deadline: float | None) -> LLMResult:
    """send(timeout) -> LLMResult. At most one retry, only on transient errors.

    deadline=None: the whole call must fit LLM_TOTAL_BUDGET_SECONDS (send gets timeout=None -> client
    default). deadline (absolute time.monotonic() value): budget_end = min(start + total budget,
    deadline); an attempt with < LLM_MIN_ATTEMPT_SECONDS left raises TimeoutError without calling the
    client, otherwise it gets timeout=min(llm_timeout_seconds, remaining); the retry needs room for
    delay + a minimal attempt."""
    started = time.monotonic()
    budget_end = started + LLM_TOTAL_BUDGET_SECONDS
    if deadline is not None:
        budget_end = min(budget_end, deadline)

    def attempt() -> LLMResult:
        if deadline is None:
            return send(None)
        remaining = budget_end - time.monotonic()
        if remaining < LLM_MIN_ATTEMPT_SECONDS:
            raise TimeoutError("LLM turn budget exhausted")
        return send(min(s.llm_timeout_seconds, remaining))

    try:
        return attempt()
    except Exception as exc:
        if not _is_transient(exc):
            raise
        now = time.monotonic()
        if deadline is None:
            if (now - started) + LLM_RETRY_DELAY + s.llm_timeout_seconds > LLM_TOTAL_BUDGET_SECONDS:
                raise
        elif now + LLM_RETRY_DELAY + LLM_MIN_ATTEMPT_SECONDS > budget_end:
            raise
        logger.warning("LLM transient error, retrying once (shop=%s, %s)", shop_id, type(exc).__name__)
    time.sleep(LLM_RETRY_DELAY)
    return attempt()


def generate(prompt, shop_id, provider: str | None = None, *, tools=None, steps=None,
             force_text: bool = False, deadline: float | None = None) -> LLMResult:
    """One LLM answer for the prompt. At most one retry, only on transient errors and only if the
    whole call still fits LLM_TOTAL_BUDGET_SECONDS (or the turn `deadline`). The last exception propagates.

    provider=None -> Settings.llm_provider (the bot path). Otherwise "claude" | "openai" overrides it
    for this call only (a copy of the settings; the cached object is never mutated); anything else
    -> ValueError. The override provider's key and model are used, same readiness check and retry.

    Stage 16: tools (neutral [{"name", "description", "parameters"}]), steps (in-turn transcript:
    [{"text", "calls": [ToolCall], "results": [{"id", "content", "is_error"}]}]), force_text (tools
    stay declared but may not be called), deadline (see _with_retry). None/False -> the old request."""
    s = _settings_for(provider)
    if s.llm_provider == "claude":
        request = build_claude_request(prompt, s.llm_model, tools=tools, steps=steps, force_text=force_text)
        send = _send_claude
    else:
        request = build_openai_request(prompt, s.llm_model, shop_id, tools=tools, steps=steps, force_text=force_text)
        send = _send_openai
    return _with_retry(s, lambda timeout: send(s, request, shop_id, timeout), shop_id, deadline)


def complete(system: str, text: str, shop_id, *, max_tokens: int, provider: str | None = None,
             deadline: float | None = None, images=None) -> LLMResult:
    """One plain call (summaries, FAQ, photo description): no tools, no cache_control, same readiness
    check / retry / deadline. images=[(bytes, mime)] (Stage 18) are filtered like generate()'s; the
    request is unchanged when there are none."""
    s = _settings_for(provider)
    if s.llm_provider == "claude":
        request = build_claude_complete_request(system, text, s.llm_model, max_tokens, images)
        send = _send_claude
    else:
        request = build_openai_complete_request(system, text, s.llm_model, max_tokens, images)
        send = _send_openai
    return _with_retry(s, lambda timeout: send(s, request, shop_id, timeout), shop_id, deadline)


def record_usage(shop_id, result: LLMResult) -> None:
    """Writes one llm_usage row. Never raises: a failed usage write must not lose the bot reply.
    service client: called from the webhook background path (no user session); shop_id comes from
    the server-side shop row, never from model output."""
    try:
        get_service_client().table("llm_usage").insert({
            "shop_id": shop_id,
            "provider": result.provider,
            "model": result.model,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cache_read_tokens": result.usage.cache_read_tokens,
            "cache_write_tokens": result.usage.cache_write_tokens,
        }).execute()
    except Exception:
        logger.warning("llm_usage write failed (shop=%s)", shop_id, exc_info=True)
