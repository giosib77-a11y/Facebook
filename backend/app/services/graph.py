"""ბოტის გრაფი (Stage 16): preprocess -> agent <-> tools -> postprocess; ერთი შესასვლელი `run_turn`.

wiring — LangGraph (`StateGraph`): S16-1 = GO (langgraph 1.2.18, Python 3.14 wheel-ები, pip-audit 0),
და მფლობელმა LangGraph ცხადად მოითხოვა (Decision Log 2026-10-28, Stage 16). გამოიყენება მხოლოდ
wiring: node-ები ჩვეულებრივი ფუნქციებია `state -> dict`, LangChain-ის ტიპები (message-ები, chat
model-ები, tool-ები) არსად არის, checkpointer არ არის, tracing არასდროს (`LANGSMITH_*` /
`LANGCHAIN_*` env production-ში არ უნდა იყოს; ტესტებში conftest შლის). `langgraph` import მხოლოდ ამ
ფაილშია. ჭერს (<=3 tool რაუნდი / <=4 LLM გამოძახება), deadline-ს და usage-ს ჩვენი კოდი აკონტროლებს;
LangGraph-ის `recursion_limit` მხოლოდ დამცავი ბადეა.

LLM-ის გამოძახება ყოველთვის `services/llm.py`-ით; prompt-ის აგება — `services/prompt.py`.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from app.services import bot, llm, replies, tools
from app.services import prompt as prompt_lib

logger = logging.getLogger("app")

NODE_NAMES = ("preprocess", "agent", "tools", "postprocess")
MAX_TOOL_ROUNDS = 3
MAX_LLM_CALLS = 4  # 1 + MAX_TOOL_ROUNDS; ბოლო (მე-4) გამოძახება იძულებით ტექსტურია
MAX_TOOL_CALLS_PER_ROUND = 3
TURN_TOOL_CHARS_BUDGET = 8000  # ერთი შეტყობინების tool შედეგების ჯამი
TURN_BUDGET_SECONDS = 45.0  # მთელი turn (ყველა LLM გამოძახება ერთად)

_RECURSION_LIMIT = 12  # მხოლოდ დამცავი ბადე: რეალური მაქსიმუმი 9 ნაბიჯია
_MIN_RESULT_CHARS = 100  # ბიუჯეტში ამაზე ნაკლები ადგილი დარჩა -> შედეგი საერთოდ არ იგზავნება

_SKIPPED = "Error: skipped, at most 3 tool calls per reply."
_OMITTED = "Result omitted: the tool budget for this message is used up. Answer with what you have."


@dataclass
class TurnResult:
    text: str
    handoff: bool = False
    route: str = "agent"  # "template" | "agent"
    calls: list = field(default_factory=list)  # ამ turn-ის llm.LLMResult-ები
    tools_used: list = field(default_factory=list)


class TurnState(TypedDict):
    shop: dict
    products: list
    message: str
    history: Any
    images: Any
    summary: Any
    provider: Any
    record_usage: bool
    refs_loader: Any
    deadline: float
    prompt: Any  # prompt_lib.Prompt | None (პირველ agent გამოძახებაზე იგება)
    steps: list
    calls: list
    pending: list
    tool_chars: int
    tools_used: list
    text: str
    handoff: bool
    route: str


def build_turn_prompt(shop, products, message, history=None, images=None, *, summary=None,
                      refs_loader=None) -> prompt_lib.Prompt:
    """Prompt ერთი turn-ისთვის. საცნობარო ფოტოები მხოლოდ კლიენტის ფოტოზე: კანდიდატები = ზუსტად ის
    ქვესიმრავლე, რასაც build_prompt ირჩევს, ამიტომ იგივე დალაგება (_sort_key) — DB-ის რიგითობა
    გარანტირებული არ არის."""
    refs = None
    if images:
        ordered = sorted(products or [], key=prompt_lib._sort_key)
        relevant = prompt_lib.select_relevant_products(ordered, message, history)
        refs = (refs_loader or bot._fetch_product_images)(relevant, images)
    return prompt_lib.build_prompt(shop, products, message, history, images, refs, summary=summary)


# ---------------------------------------------------------------------------
# node-ები: state -> ცვლილებების dict
# ---------------------------------------------------------------------------
def preprocess_node(state: TurnState) -> dict:
    """შაბლონური პასუხი (მისალმება / მადლობა / ოპერატორი) LLM-ის გარეშე. ფოტოიან შეტყობინებაზე — არასდროს."""
    if state["images"]:
        return {"route": "agent"}
    match = replies.match_template(state["message"], state["shop"].get("bot_language"))
    if match is None:
        return {"route": "agent"}
    return {"route": "template", "text": match.reply, "handoff": match.handoff}


def agent_node(state: TurnState) -> dict:
    """ზუსტად ერთი llm.generate. usage იწერება მაშინვე (turn-ის შუაში შეცდომისასაც აღრიცხულია)."""
    shop = state["shop"]
    turn_prompt = state["prompt"]
    if turn_prompt is None:  # ფოტოები ერთხელ, პირველ გამოძახებაზე
        turn_prompt = build_turn_prompt(
            shop, state["products"], state["message"], state["history"], state["images"],
            summary=state["summary"], refs_loader=state["refs_loader"],
        )
    force_text = len(state["calls"]) == MAX_LLM_CALLS - 1
    result = llm.generate(
        turn_prompt, shop["id"], state["provider"], tools=list(tools.TOOL_SPECS),
        steps=state["steps"], force_text=force_text, deadline=state["deadline"],
    )
    if state["record_usage"]:
        llm.record_usage(shop["id"], result)
    update = {"prompt": turn_prompt, "calls": [*state["calls"], result]}
    if any(c.name == tools.HUMAN_TOOL for c in result.tool_calls):
        # request_human ამთავრებს turn-ს: სხვა call-ები იგნორდება, LLM აღარ იძახება
        text = result.text.strip() or replies.handoff_reply(shop.get("bot_language"))
        return {**update, "handoff": True, "text": text, "pending": []}
    return {**update, "text": result.text, "pending": list(result.tool_calls)}


def tools_node(state: TurnState) -> dict:
    """pending call-ების შესრულება; ყოველ call-ს ზუსტად ერთი შედეგი აქვს (provider-ის მოთხოვნა)."""
    pending = state["pending"]
    ctx = tools.ToolContext(state["shop"], state["products"])
    used = state["tool_chars"]
    results = []
    for index, call in enumerate(pending):
        if index >= MAX_TOOL_CALLS_PER_ROUND:
            content, is_error = _SKIPPED, True
        elif call.arguments is None:
            content, is_error = f"Error: invalid arguments for {call.name}.", True
        else:
            outcome = tools.execute(call.name, call.arguments, ctx)
            content, is_error = outcome.content, outcome.is_error
            room = TURN_TOOL_CHARS_BUDGET - used
            if room < _MIN_RESULT_CHARS:
                content = _OMITTED
            else:
                if len(content) > room:
                    content = content[:room - 1].rstrip() + "…"
                used += len(content)
        results.append({"id": call.id, "content": content, "is_error": is_error})
    step = {"text": state["text"], "calls": pending, "results": results}
    return {
        "steps": [*state["steps"], step],
        "tools_used": [*state["tools_used"], *(c.name for c in pending[:MAX_TOOL_CALLS_PER_ROUND])],
        "tool_chars": used,
        "pending": [],
    }


def postprocess_node(state: TurnState) -> dict:
    """markdown-ის გასუფთავება. ცარიელი რჩება "" (webhook-ის FA-12); handoff-ზე — ოპერატორის ფრაზა."""
    text = replies.clean_reply(state["text"])
    if not text and state["handoff"]:
        text = replies.handoff_reply(state["shop"].get("bot_language"))
    return {"text": text}


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------
def route_after_preprocess(state: TurnState) -> str:
    return "end" if state["route"] == "template" else "agent"


def route_after_agent(state: TurnState) -> str:
    if state["pending"] and not state["handoff"] and len(state["calls"]) < MAX_LLM_CALLS:
        return "tools"
    return "postprocess"


def _build_graph():
    graph = StateGraph(TurnState)
    graph.add_node("preprocess", preprocess_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("postprocess", postprocess_node)
    graph.add_edge(START, "preprocess")
    graph.add_conditional_edges("preprocess", route_after_preprocess, {"agent": "agent", "end": END})
    graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "postprocess": "postprocess"})
    graph.add_edge("tools", "agent")
    graph.add_edge("postprocess", END)
    return graph.compile()


_GRAPH = _build_graph()


def run_turn(shop, products, message, history=None, images=None, *, summary=None, provider=None,
             record_usage: bool = True, refs_loader: Callable | None = None) -> TurnResult:
    """ერთი შემოსული შეტყობინების დამუშავება. LLM-ის შეცდომა / TimeoutError / RuntimeError (key არ არის)
    ვრცელდება — webhook-ის fallback და /test-chat-ის 502/503 გამომძახებელშია.

    refs_loader(relevant, images) -> [(label, (bytes, mime))]; default — bot._fetch_product_images.
    record_usage=False — შედარების სკრიპტისთვის (llm_usage არ იწერება)."""
    started = time.monotonic()
    state: TurnState = {
        "shop": shop, "products": products or [], "message": message, "history": history,
        "images": images, "summary": summary, "provider": provider, "record_usage": record_usage,
        "refs_loader": refs_loader, "deadline": started + TURN_BUDGET_SECONDS, "prompt": None,
        "steps": [], "calls": [], "pending": [], "tool_chars": 0, "tools_used": [],
        "text": "", "handoff": False, "route": "agent",
    }
    final = _GRAPH.invoke(state, config={"recursion_limit": _RECURSION_LIMIT})
    result = TurnResult(
        text=final["text"], handoff=final["handoff"], route=final["route"],
        calls=final["calls"], tools_used=final["tools_used"],
    )
    logger.info(
        "bot turn: route=%s calls=%d tools=%s handoff=%s %.1fs (shop=%s)",
        result.route, len(result.calls), ",".join(result.tools_used) or "-", result.handoff,
        time.monotonic() - started, shop.get("id"),
    )
    return result
