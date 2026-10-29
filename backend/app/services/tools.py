"""Bot tools (Stage 16): static specs + executors. Pure: no SDK, no LLM, no DB, no network.

Tenant isolation is structural: the executors read the shop and its products ONLY from the
ToolContext, which the caller (graph state) built from the shop the webhook resolved. A tool
argument is never a shop id and never a lookup key into storage; any argument outside the
schema (e.g. "shop_id") is rejected.

`request_human` is terminal and handled by the graph itself; here it only has a spec.
"""
import logging
import re
from dataclasses import dataclass

from app.services import prompt

logger = logging.getLogger("app.tools")

HUMAN_TOOL = "request_human"
TOOL_RESULT_MAX_CHARS = 3000

_QUERY_MAX_CHARS = 200
_QUERY_ECHO_CHARS = 100
_PRODUCT_LIMIT = 10
_KNOWLEDGE_WINDOW = 800
_KNOWLEDGE_TOP = 3
_HANDOFF_REASONS = ["customer_request", "complaint", "cannot_help", "other"]


def _query_param(what: str) -> dict:
    return {"type": "string", "description": f"Short search words (a product name, a colour, a size, a topic) to look for in {what}."}


def _spec(name: str, description: str, properties: dict) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


# Provider-neutral and static (no shop data): the tool definitions are part of the cached prefix.
TOOL_SPECS = (
    _spec(
        "search_products",
        "Search the shop's product catalogue by keywords. Use it only when the product the customer "
        "asks about is not in the inventory shown to you. Returns up to 10 matching products with "
        "price and stock.",
        {"query": _query_param("the product catalogue")},
    ),
    _spec(
        "search_knowledge",
        "Search the shop's knowledge document (delivery, payment, warranty, returns, opening hours) "
        "by keywords. Use it only when the answer is not in the shop knowledge shown to you. "
        "Returns the best matching excerpts.",
        {"query": _query_param("the shop knowledge")},
    ),
    _spec(
        "order_link",
        "Get the link where the customer can place an order. Use it when the customer is ready to "
        "buy or asks how to order.",
        {},
    ),
    _spec(
        HUMAN_TOOL,
        "Hand the conversation over to a human operator. Use it only when you cannot help, the "
        "customer asks for a human, or the customer complains. In the same reply, also tell the "
        "customer that an operator will contact them.",
        {"reason": {"type": "string", "enum": _HANDOFF_REASONS,
                    "description": "Why a human is needed."}},
    ),
)

_PARAM_KEYS = {s["name"]: frozenset(s["parameters"]["properties"]) for s in TOOL_SPECS}


@dataclass(frozen=True)
class ToolContext:
    shop: dict
    products: list


@dataclass
class ToolOutcome:
    content: str
    is_error: bool = False


def _error(text: str) -> ToolOutcome:
    return ToolOutcome(text, True)


def _cap(text: str) -> str:
    """Result size cap: cut at a line boundary when possible, never more than the limit."""
    if len(text) <= TOOL_RESULT_MAX_CHARS:
        return text
    cut = text[:TOOL_RESULT_MAX_CHARS - 1]
    nl = cut.rfind("\n")
    if nl > 0:
        cut = cut[:nl]
    return cut.rstrip() + "…"


def _valid_query(arguments: dict) -> str | None:
    query = arguments.get("query")
    if not isinstance(query, str):
        return None
    query = query.strip()
    return query if 1 <= len(query) <= _QUERY_MAX_CHARS else None


def _search_products(query: str, ctx: ToolContext) -> str:
    products = ctx.products or []
    shown = query[:_QUERY_ECHO_CHARS]
    matches = prompt.match_products(products, query, _PRODUCT_LIMIT)
    if not matches:
        return f'No products match "{shown}". The catalogue has {len(products)} products.'
    currency = prompt.currency_of(ctx.shop)
    lines = "\n".join(prompt.product_line(p, currency) for p in matches)
    return f'Products matching "{shown}" ({len(matches)} of {len(products)} in the catalogue):\n{lines}'


def _line_chunks(para: str) -> list[str]:
    """A long paragraph (pypdf returns a whole page as one paragraph with single newlines):
    lines packed greedily into <= window chunks; a line is never cut unless it is itself too long."""
    chunks: list[str] = []
    cur = ""
    for line in para.split("\n"):
        line = line.strip()
        if not line:
            continue
        if len(line) > _KNOWLEDGE_WINDOW:
            if cur:
                chunks.append(cur)
                cur = ""
            for i in range(0, len(line), _KNOWLEDGE_WINDOW):
                chunks.append(line[i:i + _KNOWLEDGE_WINDOW])
        elif cur and len(cur) + 1 + len(line) > _KNOWLEDGE_WINDOW:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def _knowledge_chunks(knowledge: str) -> list[str]:
    chunks: list[str] = []
    for para in re.split(r"\n\s*\n", knowledge):
        para = para.strip()
        if len(para) <= _KNOWLEDGE_WINDOW:
            if para:
                chunks.append(para)
        else:
            chunks.extend(_line_chunks(para))
    return chunks


def _stem(token: str) -> str:
    """Rough Georgian stem: drop the last 2 letters of a long token (case endings), keep >= 4.
    მიწოდება / მიწოდების -> მიწოდე, თბილისში / თბილისი -> თბილის. A heuristic, not morphology."""
    return token[:max(4, len(token) - 2)] if len(token) >= 6 else token


def _search_knowledge(query: str, ctx: ToolContext) -> str:
    # The FULL text, not the 20000-char clip of the SHOP block.
    knowledge = ctx.shop.get("knowledge")
    if not isinstance(knowledge, str) or not knowledge.strip():
        return "The shop has no knowledge document."
    terms = {_stem(t) for t in prompt.query_tokens(query)}
    scored = []
    for pos, chunk in enumerate(_knowledge_chunks(knowledge)):
        low = chunk.lower()
        score = sum(1 for t in terms if t in low)
        if score:
            scored.append((-score, pos, chunk))
    if not scored:
        return "No matching information in the shop knowledge."
    scored.sort(key=lambda x: (x[0], x[1]))
    excerpts = [chunk for _, _, chunk in scored[:_KNOWLEDGE_TOP]]
    return f'Shop knowledge excerpts for "{query[:_QUERY_ECHO_CHARS]}":\n' + "\n---\n".join(excerpts)


def execute(name, arguments, ctx: ToolContext) -> ToolOutcome:
    """Runs one tool call. Never raises. shop / products come only from ctx."""
    try:
        if not isinstance(name, str) or name not in _PARAM_KEYS:
            return _error("Error: unknown tool.")
        if name == HUMAN_TOOL:
            return _error("Error: handled by the system.")
        if not isinstance(arguments, dict) or set(arguments) != _PARAM_KEYS[name]:
            return _error(f"Error: invalid arguments for {name}.")
        if name == "order_link":
            return ToolOutcome("Order link: " + prompt.order_link_for(ctx.shop))
        query = _valid_query(arguments)
        if query is None:
            return _error(f"Error: invalid arguments for {name}.")
        text = _search_products(query, ctx) if name == "search_products" else _search_knowledge(query, ctx)
        return ToolOutcome(_cap(text))
    except Exception as exc:  # noqa: BLE001 — a tool failure must never break the turn
        logger.warning("tool %s failed (%s)", name if isinstance(name, str) else "?", type(exc).__name__)
        return _error("Error: tool failed.")
