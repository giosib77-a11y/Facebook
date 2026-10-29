"""S16-6: services/graph.py — preprocess -> agent <-> tools -> postprocess, `run_turn`.

Fake Claude / OpenAI SDK clients (tool calls included) + fake clock + fake usage DB are wired into
the real llm / prompt / tools / replies modules. No network, no real key, no .env.
"""
import json
import logging
import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.facebook as facebook
from app.config import get_settings
from app.services import graph, llm, prompt, replies, tools
from app.services.prompt import _sort_key
from tests.conftest import FakeSupabase

SHOP_ID = str(uuid.uuid4())
SHOP = {"id": SHOP_ID, "name": "Tbilisi Style", "description": "Clothes", "currency": "GEL",
        "knowledge": "Delivery in Tbilisi: 5 GEL."}
LAYER1_FIXTURE = (Path(__file__).parent / "fixtures" / "prompt_layer1.txt").read_text(
    encoding="utf-8").replace("\r\n", "\n")
GENERIC_QUESTION = "this item arrived broken and I am very unhappy"  # no template, no tool needed

SHOP_PRODUCTS = [
    {"id": "0001", "name": "Red Shirt", "price": 30, "quantity": 2, "sku": "RS1", "description": "cotton"},
    {"id": "0002", "name": "Blue Jeans", "price": 80, "quantity": 1, "sku": "BJ1", "description": "denim"},
]
JEANS_LINE = prompt.product_line(SHOP_PRODUCTS[1], "GEL")


def _products(n):
    return [
        {"id": f"{i:04d}", "name": f"Item {i}", "price": 10 + i, "quantity": 1 + i % 3,
         "sku": f"S{i}", "description": f"desc {i}"}
        for i in range(n)
    ]


def _stable_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Harness:
    """Fake SDK client for one provider flavour. `script` = responses (or exceptions) in call order;
    `default(n)` answers once the script is empty (n = number of requests so far)."""

    def __init__(self, monkeypatch, flavour="claude", **settings_update):
        self.flavour = flavour
        self.requests = []
        self.factory_calls = 0
        self.script = []
        self.default = None
        self.duration = 0.0  # simulated seconds each create() takes
        self.clock = FakeClock()
        self.usage_db = FakeSupabase()
        self.monkeypatch = monkeypatch
        monkeypatch.setattr(llm, "time", SimpleNamespace(monotonic=self.clock.monotonic, sleep=self.clock.sleep))
        monkeypatch.setattr(graph, "time", SimpleNamespace(monotonic=self.clock.monotonic))
        monkeypatch.setattr(llm, "get_service_client", lambda: self.usage_db)
        self.set_settings(**settings_update)

        def create(**kwargs):
            self.requests.append(kwargs)
            self.clock.now += self.duration
            if self.script:
                item = self.script.pop(0)
            elif self.default is not None:
                item = self.default(len(self.requests))
            else:
                raise AssertionError("unexpected LLM call")
            if isinstance(item, Exception):
                raise item
            return item

        def factory(s):
            self.factory_calls += 1
            return SimpleNamespace(messages=SimpleNamespace(create=create),
                                   responses=SimpleNamespace(create=create))

        monkeypatch.setattr(llm, "_anthropic_client", factory)
        monkeypatch.setattr(llm, "_openai_client", factory)

    def set_settings(self, **update):
        s = get_settings().model_copy(update=update)
        self.monkeypatch.setattr(llm, "get_settings", lambda: s)
        self.settings = s
        return s

    # -- responses ---------------------------------------------------------------------------
    def text(self, text="  Hello!  "):
        return self.calls(text=text)

    def calls(self, *calls, text=""):
        """calls: (id, name, args); args a dict, or a str for a broken (non-object) argument."""
        if self.flavour == "claude":
            content = [SimpleNamespace(type="text", text=text)] if text else []
            content += [SimpleNamespace(type="tool_use", id=i, name=n, input=a) for i, n, a in calls]
            return SimpleNamespace(
                content=content, stop_reason="tool_use" if calls else "end_turn",
                usage=SimpleNamespace(input_tokens=11, output_tokens=6, cache_read_input_tokens=4,
                                      cache_creation_input_tokens=2),
            )
        output = [
            SimpleNamespace(type="function_call", call_id=i, name=n,
                            arguments=a if isinstance(a, str) else json.dumps(a))
            for i, n, a in calls
        ]
        return SimpleNamespace(
            output_text=text, output=output,
            usage=SimpleNamespace(input_tokens=50, output_tokens=7,
                                  input_tokens_details=SimpleNamespace(cached_tokens=20, cache_write_tokens=10)),
        )

    # -- request accessors -------------------------------------------------------------------
    @property
    def none_choice(self):
        return {"type": "none"} if self.flavour == "claude" else "none"

    def tool_names(self, request):
        return [t["name"] for t in request["tools"]]

    def tool_outputs(self, request):
        out = []
        if self.flavour == "claude":
            for m in request["messages"]:
                if m["role"] == "user" and isinstance(m["content"], list):
                    for b in m["content"]:
                        if b.get("type") == "tool_result":
                            out.append({"id": b["tool_use_id"], "content": b["content"],
                                        "is_error": b.get("is_error", False)})
        else:
            for item in request["input"]:
                if item.get("type") == "function_call_output":
                    out.append({"id": item["call_id"], "content": item["output"], "is_error": None})
        return out

    def system_part(self, request):
        return request["system"] if self.flavour == "claude" else request["input"][0]

    def layer1(self, request):
        if self.flavour == "claude":
            return request["system"][0]["text"]
        return request["input"][0]["content"][0]["text"]

    def first_history_text(self, request):
        if self.flavour == "claude":
            return request["messages"][0]["content"][0]["text"]
        return request["input"][1]["content"]

    def usage_rows(self):
        return self.usage_db.calls_for("llm_usage", "insert")


@pytest.fixture(params=["claude", "openai"])
def h(request, monkeypatch):
    if request.param == "claude":
        return Harness(monkeypatch)
    return Harness(monkeypatch, "openai", llm_provider="openai", openai_api_key="test-openai-key-not-real")


@pytest.fixture
def hc(monkeypatch):
    return Harness(monkeypatch)


@pytest.fixture
def ho(monkeypatch):
    return Harness(monkeypatch, "openai", llm_provider="openai", openai_api_key="test-openai-key-not-real")


def run(message=GENERIC_QUESTION, *, shop=SHOP, products=None, **kwargs):
    return graph.run_turn(shop, SHOP_PRODUCTS if products is None else products, message, **kwargs)


# ---------------------------------------------------------------------------
# (1) preprocess: templates never reach the LLM
# ---------------------------------------------------------------------------
TEMPLATE_CASES = [
    ("გამარჯობა!", "ka", "greeting", False),
    ("Thanks 😊", "en", "thanks", False),
    ("спасибо", "ru", "thanks", False),
    ("ოპერატორი", "ka", "operator", True),
    ("talk to a human", "en", "operator", True),
    ("оператора", "auto", "operator", True),
]


@pytest.mark.parametrize("message, lang, intent, handoff", TEMPLATE_CASES)
def test_template_never_calls_llm_or_records_usage(h, message, lang, intent, handoff):
    expected = replies.match_template(message, lang)
    assert expected is not None and expected.intent == intent  # the case really is a template
    result = run(message, shop={**SHOP, "bot_language": lang})
    assert result.route == "template"
    assert result.text == expected.reply
    assert result.handoff is handoff is expected.handoff
    assert result.calls == [] and result.tools_used == []
    assert h.requests == [] and h.factory_calls == 0
    assert h.usage_rows() == []


def test_template_language_follows_bot_language(h):
    assert run("გამარჯობა", shop={**SHOP, "bot_language": "ka"}).text == "გამარჯობა! 😊 რით შემიძლია დაგეხმაროთ?"
    assert run("გამარჯობა", shop={**SHOP, "bot_language": "en"}).text == "Hello! 😊 How can I help you?"
    assert run("hello", shop={**SHOP, "bot_language": "ru"}).text == "Здравствуйте! 😊 Чем могу помочь?"
    assert run("hello", shop={**SHOP, "bot_language": "auto"}).text == "Hello! 😊 How can I help you?"
    assert h.requests == []


def test_template_works_without_an_llm_key(hc):
    hc.set_settings(anthropic_api_key="")
    assert run("გამარჯობა").route == "template"
    assert hc.factory_calls == 0


def test_greeting_with_a_photo_goes_to_the_agent(h):
    h.script = [h.text("Nice photo")]
    result = run("გამარჯობა", images=[(b"photo", "image/jpeg")], refs_loader=lambda relevant, images: [])
    assert result.route == "agent" and result.text == "Nice photo"
    assert len(h.requests) == 1 and len(h.usage_rows()) == 1


def test_long_message_with_a_greeting_goes_to_the_agent(h):
    h.script = [h.text("Red Shirt - 30 GEL")]
    result = run("გამარჯობა, წითელი მაისური გაქვთ?")
    assert result.route == "agent" and len(h.requests) == 1


# ---------------------------------------------------------------------------
# (2) one plain answer
# ---------------------------------------------------------------------------
def test_text_answer_is_one_call_with_all_tools(h):
    h.script = [h.text("  **Hello** [shop](https://a.example/x)  ")]
    result = run()
    assert len(h.requests) == 1
    request = h.requests[0]
    assert h.tool_names(request) == [s["name"] for s in tools.TOOL_SPECS]
    assert [t["name"] for t in request["tools"]] == [
        "search_products", "search_knowledge", "order_link", "request_human"]
    assert "tool_choice" not in request
    assert result.text == "Hello shop: https://a.example/x"  # postprocess: markdown cleaned
    assert result.route == "agent" and result.handoff is False and result.tools_used == []
    assert len(result.calls) == 1 and isinstance(result.calls[0], llm.LLMResult)
    assert len(h.usage_rows()) == 1


def test_record_usage_false_writes_no_row(h):
    h.script = [h.text("Hello")]
    result = run(record_usage=False)
    assert result.text == "Hello"
    assert h.usage_rows() == []
    assert len(result.calls) == 1


def test_empty_model_text_stays_empty(h):
    h.script = [h.text("")]
    result = run()
    assert result.text == "" and result.handoff is False


def test_old_handoff_mark_in_text_is_stripped_and_does_not_trigger_handoff(h):
    h.script = [h.text("Sorry, I cannot help. [[HANDOFF]]")]
    result = run()
    assert result.text == "Sorry, I cannot help." and result.handoff is False


# ---------------------------------------------------------------------------
# (3) one search round
# ---------------------------------------------------------------------------
def test_one_search_round_is_two_calls(h):
    h.script = [
        h.calls(("c1", "search_products", {"query": "jeans"}), text="Let me check"),
        h.text("Blue Jeans: 80 GEL"),
    ]
    result = run()
    assert len(h.requests) == 2
    outputs = h.tool_outputs(h.requests[1])
    assert [o["id"] for o in outputs] == ["c1"]
    assert JEANS_LINE in outputs[0]["content"]
    assert h.tool_outputs(h.requests[0]) == []
    assert result.text == "Blue Jeans: 80 GEL"  # the preamble of the tool-using answer is not sent
    assert result.tools_used == ["search_products"]
    assert len(result.calls) == 2 and len(h.usage_rows()) == 2
    assert all(row.payload["shop_id"] == SHOP_ID for row in h.usage_rows())
    assert "tool_choice" not in h.requests[0] and "tool_choice" not in h.requests[1]


def test_preamble_text_is_part_of_the_transcript_of_the_next_call(hc):
    hc.script = [hc.calls(("c1", "order_link", {}), text="One moment"), hc.text("Here it is")]
    run()
    assistant = hc.requests[1]["messages"][-2]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0] == {"type": "text", "text": "One moment"}
    assert assistant["content"][1]["type"] == "tool_use" and assistant["content"][1]["id"] == "c1"


def test_order_link_tool_result_is_the_shops_link(h):
    h.script = [h.calls(("c1", "order_link", {})), h.text("Link sent")]
    run()
    (output,) = h.tool_outputs(h.requests[1])
    assert output["content"] == "Order link: " + prompt.order_link_for(SHOP)


# ---------------------------------------------------------------------------
# (4) request_human ends the turn
# ---------------------------------------------------------------------------
def test_request_human_with_model_text(h):
    text = "ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏"
    h.script = [h.calls(("h1", "request_human", {"reason": "complaint"}), text=text)]
    result = run()
    assert len(h.requests) == 1  # no further LLM call
    assert result.handoff is True and result.text == text and result.route == "agent"
    assert len(h.usage_rows()) == 1


@pytest.mark.parametrize("lang, expected", [
    ("auto", replies.handoff_reply("auto")),
    (None, replies.handoff_reply(None)),
    ("en", "One moment, an operator will contact you shortly 🙏"),
    ("ru", "Одну минуту, оператор скоро с вами свяжется 🙏"),
])
def test_request_human_without_text_uses_the_operator_phrase(h, lang, expected):
    h.script = [h.calls(("h1", "request_human", {"reason": "cannot_help"}))]
    result = run(shop={**SHOP, "bot_language": lang})
    assert result.handoff is True and result.text == expected and expected
    assert len(h.requests) == 1


def test_auto_language_handoff_phrase_is_georgian(h):
    h.script = [h.calls(("h1", "request_human", {"reason": "other"}))]
    assert run(shop={**SHOP, "bot_language": "auto"}).text == "ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏"


def test_other_calls_in_the_same_answer_are_ignored_after_request_human(h):
    h.script = [h.calls(("a", "search_products", {"query": "jeans"}), ("h", "request_human", {"reason": "other"}))]
    result = run()
    assert len(h.requests) == 1
    assert result.handoff is True
    assert result.tools_used == []  # search_products was not executed


def test_request_human_text_made_only_of_an_old_mark_falls_back_to_the_operator_phrase(h):
    h.script = [h.calls(("h", "request_human", {"reason": "other"}), text="[[HANDOFF]]")]
    result = run()
    assert result.handoff is True and result.text == replies.handoff_reply(None)


# ---------------------------------------------------------------------------
# (5) the call cap: at most 4 LLM calls, the 4th is forced to text
# ---------------------------------------------------------------------------
def test_cap_is_four_calls_three_tool_rounds_and_the_last_is_forced_text(h):
    h.default = lambda n: h.calls((f"c{n}", "search_products", {"query": "jeans"}))
    result = run()
    assert len(h.requests) == graph.MAX_LLM_CALLS == 4
    assert len(result.calls) == 4 and len(h.usage_rows()) == 4
    assert result.tools_used == ["search_products"] * graph.MAX_TOOL_ROUNDS
    for request in h.requests[:3]:
        assert "tool_choice" not in request
    assert h.requests[3]["tool_choice"] == h.none_choice
    assert h.requests[3]["tools"]  # tools stay declared (the cached prefix does not change)
    # the model ignored `none` and asked for a tool again: the turn ends, the text may be empty
    assert result.text == ""
    # every tool_use had exactly one result, in the transcript of the last request
    assert [o["id"] for o in h.tool_outputs(h.requests[3])] == ["c1", "c2", "c3"]


def test_cap_leaves_a_text_answer_of_the_forced_call(h):
    h.script = [h.calls((f"c{n}", "search_products", {"query": "jeans"})) for n in (1, 2, 3)]
    h.script.append(h.text("Final answer"))
    result = run()
    assert len(h.requests) == 4 and result.text == "Final answer"


# ---------------------------------------------------------------------------
# (6) at most 3 executed tool calls per answer; every call gets a result
# ---------------------------------------------------------------------------
def test_five_calls_in_one_answer_three_run_two_are_skipped(h):
    h.script = [
        h.calls(*[(f"c{i}", "search_products", {"query": "jeans"}) for i in range(5)]),
        h.text("Done"),
    ]
    result = run()
    outputs = h.tool_outputs(h.requests[1])
    assert [o["id"] for o in outputs] == [f"c{i}" for i in range(5)]
    assert all(JEANS_LINE in o["content"] for o in outputs[:3])
    assert [o["content"] for o in outputs[3:]] == ["Error: skipped, at most 3 tool calls per reply."] * 2
    if h.flavour == "claude":
        assert [o["is_error"] for o in outputs] == [False, False, False, True, True]
    assert result.tools_used == ["search_products"] * 3  # only executed calls are reported
    assert len(h.requests) == 2


# ---------------------------------------------------------------------------
# (7) tool result budget per turn
# ---------------------------------------------------------------------------
def test_tool_results_stay_within_the_turn_budget(h):
    knowledge = "\n\n".join(f"Delivery rule {i}: " + "x" * 770 for i in range(6))
    shop = {**SHOP, "knowledge": knowledge}
    round_of_three = [(f"k{i}", "search_knowledge", {"query": "delivery"}) for i in range(3)]
    round_two = [(f"m{i}", "search_knowledge", {"query": "delivery"}) for i in range(3)]
    h.script = [h.calls(*round_of_three), h.calls(*round_two), h.text("Enough")]
    result = run(shop=shop)
    assert len(h.requests) == 3
    outputs = h.tool_outputs(h.requests[2])
    assert len(outputs) == 6
    omitted_text = "Result omitted: the tool budget for this message is used up. Answer with what you have."
    real = [o["content"] for o in outputs if o["content"] != omitted_text]
    assert 0 < len(real) < 6 and any(o["content"] == omitted_text for o in outputs)
    assert sum(len(c) for c in real) <= graph.TURN_TOOL_CHARS_BUDGET
    assert all(len(c) <= tools.TOOL_RESULT_MAX_CHARS for c in real)
    assert result.text == "Enough"


def _request_chars(request) -> tuple[int, list[str]]:
    """Every text the model receives in one request: system / message text, tool_use input (as JSON),
    tool results, and the tool declarations (as JSON). Returns (total, the pieces)."""
    pieces = []
    if "system" in request:  # Claude
        pieces += [b["text"] for b in request["system"]]
        for m in request["messages"]:
            for b in m["content"]:
                if b["type"] == "text":
                    pieces.append(b["text"])
                elif b["type"] == "tool_use":
                    pieces.append(json.dumps(b["input"]))
                elif b["type"] == "tool_result":
                    pieces.append(b["content"])
    else:  # OpenAI
        for item in request["input"]:
            if item.get("type") == "function_call":
                pieces.append(item["arguments"])
            elif item.get("type") == "function_call_output":
                pieces.append(item["output"])
            elif isinstance(item["content"], str):
                pieces.append(item["content"])
            else:
                pieces += [p["text"] for p in item["content"] if p["type"] == "input_text"]
    pieces.append(json.dumps(request["tools"]))
    return sum(len(p) for p in pieces), pieces


def test_worst_case_turn_requests_stay_bounded_and_never_carry_the_whole_knowledge(h):
    # S17-5: maximal products, 50 000-char knowledge WITHOUT a FAQ (the fallback is the worse case),
    # 40 x 2000 history, 2000-char message, 3 rounds x 3 search_knowledge calls of 3000-char results.
    huge = "x" * 100_000
    paragraphs = [f"Delivery rule {i:03d}: " + "d" * 770 for i in range(62)]
    paragraphs.append("zzmarker49k " + "m" * 770)  # matches no search: it must never reach a request
    knowledge = "\n\n".join(paragraphs)
    assert 49_000 < len(knowledge) <= 50_000
    shop = {**SHOP, "name": huge, "description": "d" * 1_000_000, "knowledge": knowledge}
    products = [{"id": f"{i:03d}", "name": huge, "sku": huge, "description": huge, "price": 10, "quantity": 1}
                for i in range(30)]
    history = []
    for i in range(20):
        history.append({"role": "user", "content": f"u{i} " + "q" * 1996})
        history.append({"role": "bot", "content": f"b{i} " + "a" * 1996})
    query = "delivery " + "q" * 191  # 200 chars
    preamble = "p" * 200
    h.script = [
        h.calls(*[(f"r{r}c{i}", "search_knowledge", {"query": query}) for i in range(3)], text=preamble)
        for r in range(3)
    ]
    h.script.append(h.text("Final"))
    result = graph.run_turn(shop, products, "m" * 2000, history)
    assert result.text == "Final" and len(h.requests) == 4
    assert result.tools_used == ["search_knowledge"] * 9

    bound = (prompt.MAX_PROMPT_CHARS + len(json.dumps(tools.TOOL_SPECS))
             + graph.TURN_TOOL_CHARS_BUDGET + 2_000)
    totals = []
    for request in h.requests:
        total, pieces = _request_chars(request)
        totals.append(total)
        assert total <= bound, (total, bound)
        assert not any("zzmarker49k" in p for p in pieces)  # past the 20000-char clip, not matched
        assert not any(knowledge[:30_000] in p for p in pieces)  # the full text is never sent
    # the real numbers (documented in the Stage 17 report)
    assert max(totals) == totals[-1]  # the last request carries the whole in-turn transcript
    outputs = h.tool_outputs(h.requests[3])
    assert len(outputs) == 9 and sum(len(o["content"]) for o in outputs
                                     if not o["content"].startswith("Result omitted")) <= graph.TURN_TOOL_CHARS_BUDGET


# ---------------------------------------------------------------------------
# (8) bad tool calls become error results, the loop goes on, no DB access by tools
# ---------------------------------------------------------------------------
def test_invalid_unknown_and_foreign_shop_calls_are_error_results(h):
    h.script = [
        h.calls(
            ("a", "search_products", "{broken json"),
            ("b", "no_such_tool", {}),
            ("c", "search_products", {"query": "jeans", "shop_id": str(uuid.uuid4())}),
        ),
        h.text("ok"),
    ]
    result = run()
    outputs = h.tool_outputs(h.requests[1])
    assert [o["id"] for o in outputs] == ["a", "b", "c"]
    assert outputs[0]["content"] == "Error: invalid arguments for search_products."
    assert outputs[1]["content"] == "Error: unknown tool."
    assert outputs[2]["content"] == "Error: invalid arguments for search_products."
    if h.flavour == "claude":
        assert all(o["is_error"] for o in outputs)
    assert result.text == "ok"
    assert {c.table for c in h.usage_db.calls} == {"llm_usage"}  # tools never touch the DB
    assert all(c.op == "insert" for c in h.usage_db.calls)


def test_openai_broken_arguments_are_sent_back_verbatim(ho):
    ho.script = [ho.calls(("a", "search_products", "{broken json")), ho.text("ok")]
    run()
    (call_item,) = [i for i in ho.requests[1]["input"] if i.get("type") == "function_call"]
    assert call_item["arguments"] == "{broken json" and call_item["call_id"] == "a"


# ---------------------------------------------------------------------------
# (9) turn deadline
# ---------------------------------------------------------------------------
def test_exhausted_turn_budget_raises_timeout_before_the_second_call(h):
    h.duration = 43.0  # the first call leaves 2 s of the 45 s turn: below LLM_MIN_ATTEMPT_SECONDS
    h.script = [h.calls(("c1", "search_products", {"query": "jeans"})), h.text("never reached")]
    with pytest.raises(TimeoutError):
        run()
    assert len(h.requests) == 1  # the second call was not even attempted
    assert len(h.usage_rows()) == 1  # usage rows = calls that completed
    assert h.requests[0]["timeout"] <= graph.TURN_BUDGET_SECONDS


def test_each_call_gets_the_remaining_turn_time_as_its_timeout(h):
    h.duration = 10.0
    h.script = [h.calls(("c1", "order_link", {})), h.text("ok")]
    run()
    assert h.requests[0]["timeout"] == min(h.settings.llm_timeout_seconds, 45.0)
    assert h.requests[1]["timeout"] == min(h.settings.llm_timeout_seconds, 35.0)


def test_turn_deadline_is_45_seconds():
    assert graph.TURN_BUDGET_SECONDS == 45.0


def test_the_last_call_gets_only_what_is_left_of_the_turn_budget(hc):
    # three rounds of 14 s: the 4th call starts at 42 s with exactly 3 s left (the minimum) and its
    # per-request timeout is capped to that remainder, so the whole turn stays inside 45 s
    hc.duration = 14.0
    hc.default = lambda n: hc.calls((f"c{n}", "order_link", {}))
    result = run()
    assert len(hc.requests) == 4
    assert hc.requests[3]["timeout"] == pytest.approx(3.0)
    assert result.text == ""


# ---------------------------------------------------------------------------
# (10) provider override
# ---------------------------------------------------------------------------
def test_provider_override_routes_every_call_to_openai(hc):
    hc.set_settings(openai_api_key="test-openai-key-not-real")  # default provider stays claude
    hc.flavour = "openai"  # the fake answers below use the OpenAI response shape
    hc.script = [hc.calls(("c1", "order_link", {})), hc.text("via openai")]
    result = run(provider="openai")
    assert len(hc.requests) == 2 and all("input" in r and "messages" not in r for r in hc.requests)
    assert result.text == "via openai"
    assert {row.payload["provider"] for row in hc.usage_rows()} == {"openai"}
    assert hc.settings.llm_provider == "claude"


# ---------------------------------------------------------------------------
# (11) owner test, end to end: tools and cached layers are byte-identical
# ---------------------------------------------------------------------------
HISTORY_A = [{"role": "user", "content": "hi"}, {"role": "bot", "content": "hello!"}]
HISTORY_B = [{"role": "user", "content": "Item 3 price?"}, {"role": "bot", "content": "13 GEL"}]


@pytest.mark.parametrize("n_products", [5, 40])
def test_tools_and_cached_layers_are_byte_identical_across_messages(h, n_products):
    products = _products(n_products)
    h.script = [h.text("Hello!"), h.text("Hello!")]
    first = run("Item 3", shop=SHOP, products=products, history=HISTORY_A)
    second = run("Item 25 please, size M?", shop=SHOP, products=products, history=HISTORY_B)
    assert first.text == second.text == "Hello!"

    a, b = h.requests
    assert _stable_bytes(a["tools"]) == _stable_bytes(b["tools"])
    assert _stable_bytes(h.system_part(a)) == _stable_bytes(h.system_part(b))
    assert h.layer1(a) == LAYER1_FIXTURE
    if h.flavour == "claude":
        assert a["system"][1]["text"].encode("utf-8") == b["system"][1]["text"].encode("utf-8")
        # SF-1: the L3 breakpoint is on the last history block, never on the variable final turn
        for r in h.requests:
            assert "cache_control" not in r
            assert r["messages"][-2]["content"][-1]["cache_control"] == {"type": "ephemeral"}
            assert all("cache_control" not in blk for blk in r["messages"][-1]["content"])
        assert a["messages"][-1] != b["messages"][-1]
        if n_products > 30:
            assert "Item 25" not in a["system"][1]["text"]
            assert "Relevant products for this message" in b["messages"][-1]["content"][0]["text"]
    else:
        assert a["input"][-1] != b["input"][-1]
        assert a["model"] == h.settings.openai_model


def test_tools_are_identical_with_and_without_tool_rounds(h):
    h.script = [h.text("one"), h.calls(("c", "order_link", {})), h.text("two")]
    run()
    run()
    first_tools, second_tools, third_tools = (r["tools"] for r in h.requests)
    assert _stable_bytes(first_tools) == _stable_bytes(second_tools) == _stable_bytes(third_tools)


def test_two_shops_share_tools_and_layer1(h):
    other = {"id": str(uuid.uuid4()), "name": "Other Shop", "currency": "USD", "knowledge": "Different."}
    h.script = [h.text("a"), h.text("b")]
    run(shop=SHOP, products=_products(5))
    run(shop=other, products=_products(3))
    a, b = h.requests
    assert _stable_bytes(a["tools"]) == _stable_bytes(b["tools"])
    assert h.layer1(a) == h.layer1(b) == LAYER1_FIXTURE
    assert _stable_bytes(h.system_part(a)) != _stable_bytes(h.system_part(b))  # L2 is per shop


def test_system_is_independent_of_product_order(h):
    products = _products(40)
    h.script = [h.text("a"), h.text("a")]
    run("Item 3", products=products)
    run("Item 3", products=list(reversed(products)))
    a, b = h.requests
    assert _stable_bytes(h.system_part(a)) == _stable_bytes(h.system_part(b))


# ---------------------------------------------------------------------------
# (12) reference photos come from the same relevant subset the prompt uses
# ---------------------------------------------------------------------------
@pytest.fixture
def downloads(monkeypatch):
    urls = []

    def fake_download(url, **kwargs):
        urls.append(url)
        return b"img-bytes", "image/jpeg"

    monkeypatch.setattr(facebook, "download_image", fake_download)
    monkeypatch.setattr(facebook, "is_own_storage_image_url", lambda url: True)
    return urls


def _photo_products(n):
    products = _products(n)
    for p in products:
        p["image_url"] = f"https://cdn.example.com/{p['id']}.jpg"
    return products


def _request_texts(request):
    return [b["text"] for b in request["messages"][-1]["content"] if b["type"] == "text"]


def test_reference_photos_follow_prompt_subset_regardless_of_db_order(hc, downloads):
    products = _photo_products(40)
    customer = [(b"customer-photo", "image/jpeg")]
    hc.default = lambda n: hc.text("Looks like Item 33")

    run("Item 33", products=products, images=customer)
    in_order = list(downloads)
    downloads.clear()
    run("Item 33", products=list(reversed(products)), images=customer)
    reversed_order = list(downloads)

    assert in_order and set(in_order) == set(reversed_order)
    for request in hc.requests:
        texts = _request_texts(request)
        relevant_block = next(t for t in texts if t.startswith("Relevant products for this message"))
        labels = [t for t in texts if t.startswith("• ")]
        assert labels
        for label in labels:
            name = label.removeprefix("• ").split(" — ")[0]
            assert f"- {name} —" in relevant_block
        assert "• Item 33 —" in "".join(labels)
    assert "https://cdn.example.com/0033.jpg" in in_order


def test_reference_candidates_use_the_prompt_sort_order(hc, downloads):
    products = list(reversed(_photo_products(40)))  # DB order is not guaranteed
    hc.script = [hc.text("ok")]
    run("something generic", products=products, images=[(b"c", "image/jpeg")])
    expected = [p["image_url"] for p in sorted(products, key=_sort_key)[:12]]
    assert sorted(downloads) == sorted(expected)  # downloads run in a thread pool: order is free


def test_no_reference_photos_downloaded_without_customer_photo(hc, downloads):
    hc.script = [hc.text("ok")]
    run("Item 3", products=_photo_products(5))
    assert downloads == []
    assert all(b["type"] == "text" for b in hc.requests[0]["messages"][-1]["content"])


def test_photos_are_loaded_once_per_turn_even_with_tool_rounds(hc):
    loads = []

    def loader(relevant, images):
        loads.append((relevant, images))
        return [("• Item 1 — 11", (b"ref", "image/jpeg"))]

    hc.script = [hc.calls(("c1", "search_products", {"query": "item"})), hc.text("It is Item 1")]
    customer = [(b"photo", "image/jpeg")]
    run("what is this?", products=_products(3), images=customer, refs_loader=loader)
    assert len(loads) == 1
    relevant, images = loads[0]
    assert images == customer and relevant == sorted(_products(3), key=_sort_key)
    # the reference photo travels in every call of the turn (the final user turn is rebuilt from the prompt)
    for request in hc.requests:
        final = next(m for m in request["messages"] if m["role"] == "user" and any(
            b["type"] == "text" and b["text"] == "• Item 1 — 11" for b in m["content"]
            if isinstance(b, dict) and "type" in b))
        assert final


def test_refs_loader_is_not_called_without_a_customer_photo(hc):
    calls = []
    hc.script = [hc.text("ok")]
    run("Item 3", products=_products(3), refs_loader=lambda *a: calls.append(a) or [])
    assert calls == []


def test_build_turn_prompt_matches_build_prompt_without_photos():
    products = _products(5)
    built = graph.build_turn_prompt(SHOP, products, "Item 2", HISTORY_A, summary="S0")
    direct = prompt.build_prompt(SHOP, products, "Item 2", HISTORY_A, None, None, summary="S0")
    assert built == direct


# ---------------------------------------------------------------------------
# (13) summary
# ---------------------------------------------------------------------------
def test_summary_goes_in_front_of_the_first_history_turn(h):
    h.script = [h.text("ok")]
    run("Item 3", products=_products(3), history=HISTORY_A, summary="S0 the customer wants a red shirt")
    first = h.first_history_text(h.requests[0])
    assert first.startswith(prompt.SUMMARY_HEADER)
    assert "S0 the customer wants a red shirt" in first and first.endswith("hi")


def test_summary_is_the_only_history_turn_when_there_is_no_history(h):
    h.script = [h.text("ok")]
    run("Item 3", products=_products(3), summary="S0")
    assert h.first_history_text(h.requests[0]) == f"{prompt.SUMMARY_HEADER}\nS0"


def test_no_summary_leaves_history_untouched(h):
    h.script = [h.text("ok")]
    run("Item 3", products=_products(3), history=HISTORY_A)
    assert h.first_history_text(h.requests[0]) == "hi"


# ---------------------------------------------------------------------------
# (14) wiring
# ---------------------------------------------------------------------------
def test_graph_has_the_four_nodes():
    assert graph.NODE_NAMES == ("preprocess", "agent", "tools", "postprocess")
    assert set(graph._GRAPH.get_graph().nodes) >= set(graph.NODE_NAMES)


def test_langgraph_is_imported_only_by_graph_py_and_langchain_nowhere():
    app_dir = Path(graph.__file__).resolve().parents[1]
    importers = set()
    for path in app_dir.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(?:from|import)\s+langchain", source, re.MULTILINE), path
        if re.search(r"^\s*(?:from|import)\s+langgraph", source, re.MULTILINE):
            importers.add(path.name)
    assert importers == {"graph.py"}


def test_tracing_env_is_off_in_tests():
    for name in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY"):
        assert name not in os.environ


@pytest.mark.parametrize("env", [
    {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "test-not-real"},
    {"LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": "test-not-real"},
    {"LANGSMITH_TRACING_V2": "true", "LANGSMITH_API_KEY": "test-not-real"},
    {"LANGCHAIN_TRACING": "true"},  # legacy var: without the fix langchain-core raises RuntimeError
    {"LANGCHAIN_HANDLER": "langchain"},
    {"LANGCHAIN_TRACING": "true", "LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "test-not-real"},
])
def test_tracing_env_by_mistake_never_creates_a_tracer_or_touches_the_network(hc, monkeypatch, env):
    """S16-12: TurnState (shop row, customer text/photos) must never reach LangSmith, whatever the env says."""
    from langchain_core.tracers.langchain import LangChainTracer
    from langsmith import Client
    from langsmith.utils import get_env_var

    created = []

    def _boom(*args, **kwargs):  # langchain-core swallows exceptions from the tracer, so record as well
        created.append(args)
        raise AssertionError("a LangSmith tracer / client was created")

    monkeypatch.setattr(LangChainTracer, "__init__", _boom)
    monkeypatch.setattr(Client, "__init__", _boom)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_env_var.cache_clear()  # langsmith caches env lookups (lru_cache) — without this the env above is ignored
    hc.script = [hc.text("Hello")]
    try:
        result = run()
    finally:
        get_env_var.cache_clear()
    assert result.text == "Hello"
    assert len(hc.requests) == 1
    assert created == []


def test_turn_logs_one_info_line_without_customer_text(hc, caplog):
    hc.script = [hc.calls(("c1", "order_link", {})), hc.text("ok")]
    with caplog.at_level(logging.INFO, logger="app"):
        run("secret customer message " + GENERIC_QUESTION)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("bot turn:")]
    assert len(lines) == 1
    assert "route=agent" in lines[0] and "calls=2" in lines[0] and "tools=order_link" in lines[0]
    assert f"shop={SHOP_ID}" in lines[0] and "secret customer message" not in lines[0]


# ---------------------------------------------------------------------------
# (15) guarantees of the old get_bot_reply level, now on run_turn
# ---------------------------------------------------------------------------
def test_usage_row_has_shop_id_and_claude_tokens(hc):
    hc.script = [hc.text("  Hello!  ")]
    assert run("hi there, how much is the red shirt?").text == "Hello!"
    (row,) = hc.usage_rows()
    assert row.payload == {
        "shop_id": SHOP_ID, "provider": "claude", "model": hc.settings.claude_model,
        "input_tokens": 11, "output_tokens": 6, "cache_read_tokens": 4, "cache_write_tokens": 2,
    }


def test_usage_row_for_openai(ho):
    ho.script = [ho.text("Hello!")]
    run(GENERIC_QUESTION)
    (row,) = ho.usage_rows()
    assert row.payload["provider"] == "openai" and row.payload["shop_id"] == SHOP_ID
    assert (row.payload["input_tokens"], row.payload["cache_read_tokens"], row.payload["cache_write_tokens"]) == (
        20, 20, 10)


def test_reply_returned_when_usage_write_fails(h, caplog):
    h.usage_db.errors[("llm_usage", "insert")] = RuntimeError("db down")
    h.script = [h.text("Hello!")]
    with caplog.at_level(logging.WARNING, logger="app"):
        assert run().text == "Hello!"
    assert any(SHOP_ID in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_no_usage_row_when_the_llm_call_fails(h):
    h.script = [ValueError("bad request")]
    with pytest.raises(ValueError):
        run()
    assert h.usage_rows() == []


def test_failure_on_the_second_call_keeps_the_first_usage_row(h):
    h.script = [h.calls(("c1", "order_link", {})), ValueError("bad request")]
    with pytest.raises(ValueError):
        run()
    assert len(h.usage_rows()) == 1


def test_not_ready_raises_runtime_error_without_building_a_client(hc):
    hc.set_settings(anthropic_api_key="")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        run()
    assert hc.factory_calls == 0 and hc.requests == []
    assert hc.usage_rows() == []


def test_not_ready_openai_names_openai_key(hc):
    hc.set_settings(llm_provider="openai", openai_api_key=" ")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        run()
    assert hc.factory_calls == 0


def test_unknown_provider_override_is_a_value_error(hc):
    with pytest.raises(ValueError):
        run(provider="gemini")
    assert hc.requests == []
