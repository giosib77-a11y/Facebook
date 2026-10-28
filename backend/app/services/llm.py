"""LLM calls for the bot: Claude (default) / OpenAI — request building, bounded retry, usage.

Takes the provider-agnostic Prompt from services/prompt.py and returns plain text + normalized
token usage. The provider is chosen by Settings.llm_provider.

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
"""
import base64
import logging
import time
from dataclasses import dataclass

from app.config import get_settings
from app.core.supabase_client import get_service_client

logger = logging.getLogger("app")

MAX_OUTPUT_TOKENS = 800
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})

LLM_RETRY_DELAY = 1.5  # seconds before the single retry (retry-after is ignored)
LLM_TOTAL_BUDGET_SECONDS = 45.0  # whole generate() call, retry included

_EMPTY_FINAL_TEXT = "(The customer sent an empty message.)"


@dataclass
class Usage:
    input_tokens: int = 0  # uncached input
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    usage: Usage


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
            data = part.get("data")
            mime = part.get("mime")
            mime = mime.strip().lower() if isinstance(mime, str) else ""
            if not data or not isinstance(data, (bytes, bytearray)):
                continue
            if mime not in ALLOWED_IMAGE_MIMES:
                logger.warning("LLM image skipped: unsupported mime type %r", mime[:40])
                continue
            if len(data) > MAX_IMAGE_BYTES:
                logger.warning("LLM image skipped: too large (%d bytes)", len(data))
                continue
            out.append(("image", mime, base64.b64encode(bytes(data)).decode("ascii")))
    if not out:
        out.append(("text", _EMPTY_FINAL_TEXT))
    return out


def build_claude_request(prompt, model: str) -> dict:
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
    return {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "thinking": {"type": "disabled"},
        "system": [
            {"type": "text", "text": prompt.layer1, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": prompt.layer2, "cache_control": {"type": "ephemeral", "ttl": "5m"}},
        ],
        "messages": messages,
    }


def build_openai_request(prompt, model: str, shop_id) -> dict:
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
    return {
        "model": model,
        "input": items,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "prompt_cache_key": f"shop:{shop_id}",
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
    cached = _tok(getattr(usage, "input_tokens_details", None), "cached_tokens")
    return Usage(
        input_tokens=max(0, _tok(usage, "input_tokens") - cached),
        output_tokens=_tok(usage, "output_tokens"),
        cache_read_tokens=cached,
        cache_write_tokens=0,
    )


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------
def _call_claude(s, prompt, shop_id) -> LLMResult:
    request = build_claude_request(prompt, s.llm_model)
    response = _anthropic_client(s).messages.create(**request)
    text = "".join(
        (getattr(b, "text", "") or "")
        for b in (getattr(response, "content", None) or [])
        if getattr(b, "type", None) == "text"
    )
    if getattr(response, "stop_reason", None) == "refusal":
        logger.warning("LLM refused to answer (shop=%s)", shop_id)
        text = ""
    return LLMResult(text, "claude", s.llm_model, _claude_usage(getattr(response, "usage", None)))


def _call_openai(s, prompt, shop_id) -> LLMResult:
    request = build_openai_request(prompt, s.llm_model, shop_id)
    response = _openai_client(s).responses.create(**request)
    text = getattr(response, "output_text", None) or ""
    return LLMResult(text, "openai", s.llm_model, _openai_usage(getattr(response, "usage", None)))


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


def generate(prompt, shop_id) -> LLMResult:
    """One LLM answer for the prompt. At most one retry, only on transient errors and only if the
    whole call still fits LLM_TOTAL_BUDGET_SECONDS. The last exception propagates."""
    s = get_settings()
    if not s.llm_ready:
        raise RuntimeError(f"LLM key not configured: {s.llm_key_env_name}")
    call = _call_claude if s.llm_provider == "claude" else _call_openai

    started = time.monotonic()
    try:
        return call(s, prompt, shop_id)
    except Exception as exc:
        if not _is_transient(exc):
            raise
        if (time.monotonic() - started) + LLM_RETRY_DELAY + s.llm_timeout_seconds > LLM_TOTAL_BUDGET_SECONDS:
            raise
        logger.warning("LLM transient error, retrying once (shop=%s, %s)", shop_id, type(exc).__name__)
    time.sleep(LLM_RETRY_DELAY)
    return call(s, prompt, shop_id)


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
