"""S16-2: llm tool calling (Claude / OpenAI), turn deadline, complete() — fake SDK clients only, no network."""
import json
from types import SimpleNamespace

import anthropic
import httpx2
import openai
import pytest

from app.services import llm
from app.services.prompt import Prompt

REQ = httpx2.Request("POST", "https://api.example.invalid/v1/x")

TOOLS = [
    {
        "name": "search_products",
        "description": "Search the catalog.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                       "required": ["query"], "additionalProperties": False},
    },
    {
        "name": "request_human",
        "description": "Hand over to a human.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
]


def _prompt(history=None, final_text="how much?"):
    return Prompt(
        layer1="LAYER ONE",
        layer2="LAYER TWO",
        history=history if history is not None else [
            {"role": "user", "text": "hi"},
            {"role": "assistant", "text": "hello"},
        ],
        final=[{"type": "text", "text": final_text}],
    )


def _steps():
    return [
        {
            "text": "Let me check.",
            "calls": [
                llm.ToolCall("tu_1", "search_products", {"query": "მაისური"}, '{"query": "მაისური"}'),
                llm.ToolCall("tu_2", "request_human", {}, "{}"),
            ],
            "results": [
                {"id": "tu_1", "content": "found 2", "is_error": False},
                {"id": "tu_2", "content": "bad call", "is_error": True},
            ],
        },
        {
            "text": "",
            "calls": [llm.ToolCall("tu_3", "search_products", None, "{not json")],
            "results": [{"id": "tu_3", "content": "invalid arguments", "is_error": True}],
        },
    ]


def _breakpoints(req):
    out = [(f"system[{i}]", b["cache_control"]) for i, b in enumerate(req["system"]) if "cache_control" in b]
    for mi, m in enumerate(req["messages"]):
        out.extend((f"messages[{mi}][{bi}]", b["cache_control"])
                   for bi, b in enumerate(m["content"]) if "cache_control" in b)
    return out


def _status_error(cls, status):
    return cls("boom", response=httpx2.Response(status, request=REQ), body=None)


def _claude_response(text="ok", content=None, stop_reason="end_turn"):
    return SimpleNamespace(
        content=content if content is not None else [SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5,
                              cache_read_input_tokens=3, cache_creation_input_tokens=2),
    )


def _openai_response(text="ok", output=None):
    return SimpleNamespace(
        output_text=text,
        output=output if output is not None else [],
        usage=SimpleNamespace(input_tokens=100, output_tokens=7,
                              input_tokens_details=SimpleNamespace(cached_tokens=40)),
    )


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Harness:
    """Fake Claude/OpenAI clients driven by `script`: items are (seconds_it_takes, result|exception)."""

    def __init__(self, monkeypatch, provider="claude"):
        self.clock = Clock()
        self.script = []
        self.requests = []
        self.factory_calls = 0
        monkeypatch.setattr(llm, "time", SimpleNamespace(monotonic=self.clock.monotonic, sleep=self.clock.sleep))
        update = {"llm_provider": provider}
        if provider == "openai":
            update["openai_api_key"] = "test-openai-key-not-real"
        self.settings = llm.get_settings().model_copy(update=update)
        monkeypatch.setattr(llm, "get_settings", lambda: self.settings)

        def create(**kwargs):
            self.requests.append(kwargs)
            duration, result = self.script.pop(0)
            self.clock.now += duration
            if isinstance(result, Exception):
                raise result
            return result

        def factory(s):
            self.factory_calls += 1
            return SimpleNamespace(
                messages=SimpleNamespace(create=create),
                responses=SimpleNamespace(create=create),
            )

        monkeypatch.setattr(llm, "_anthropic_client", factory)
        monkeypatch.setattr(llm, "_openai_client", factory)

    @property
    def attempts(self):
        return len(self.requests)


# ---------------------------------------------------------------------------
# (1) Claude tools
# ---------------------------------------------------------------------------
def test_claude_tools_conversion_and_no_cache_control_on_tools():
    req = llm.build_claude_request(_prompt(), "m", tools=TOOLS)
    assert req["tools"] == [
        {"name": "search_products", "description": "Search the catalog.", "input_schema": TOOLS[0]["parameters"]},
        {"name": "request_human", "description": "Hand over to a human.", "input_schema": TOOLS[1]["parameters"]},
    ]
    assert all("cache_control" not in t for t in req["tools"])
    assert "tool_choice" not in req


def test_claude_breakpoints_unchanged_by_tools_and_steps():
    plain = llm.build_claude_request(_prompt(), "m")
    with_tools = llm.build_claude_request(_prompt(), "m", tools=TOOLS)
    with_steps = llm.build_claude_request(_prompt(), "m", tools=TOOLS, steps=_steps(), force_text=True)
    expected = [
        ("system[0]", {"type": "ephemeral", "ttl": "1h"}),
        ("system[1]", {"type": "ephemeral", "ttl": "5m"}),
        ("messages[1][0]", {"type": "ephemeral"}),
    ]
    assert _breakpoints(plain) == _breakpoints(with_tools) == _breakpoints(with_steps) == expected


def test_claude_force_text_sets_tool_choice_none():
    req = llm.build_claude_request(_prompt(), "m", tools=TOOLS, force_text=True)
    assert req["tool_choice"] == {"type": "none"}
    assert "tools" in req


# ---------------------------------------------------------------------------
# (2) Claude steps
# ---------------------------------------------------------------------------
def test_claude_steps_transcript_after_final_turn():
    req = llm.build_claude_request(_prompt(), "m", tools=TOOLS, steps=_steps())
    msgs = req["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "user", "assistant", "user"]
    assert msgs[2]["content"] == [{"type": "text", "text": "how much?"}]  # final turn, no breakpoint
    assert msgs[3] == {"role": "assistant", "content": [
        {"type": "text", "text": "Let me check."},
        {"type": "tool_use", "id": "tu_1", "name": "search_products", "input": {"query": "მაისური"}},
        {"type": "tool_use", "id": "tu_2", "name": "request_human", "input": {}},
    ]}
    # is_error only on errors: both results of step 1 -> second one is an error, first is not
    assert msgs[4] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tu_1", "content": "found 2"},
        {"type": "tool_result", "tool_use_id": "tu_2", "content": "bad call", "is_error": True},
    ]}
    # empty text -> no text block; arguments None -> {}
    assert msgs[5] == {"role": "assistant", "content": [
        {"type": "tool_use", "id": "tu_3", "name": "search_products", "input": {}},
    ]}
    assert msgs[6]["content"] == [
        {"type": "tool_result", "tool_use_id": "tu_3", "content": "invalid arguments", "is_error": True},
    ]


def test_claude_steps_have_no_cache_control_and_history_breakpoint_stays():
    req = llm.build_claude_request(_prompt(), "m", steps=_steps())
    positions = [w for w, _ in _breakpoints(req)]
    assert positions == ["system[0]", "system[1]", "messages[1][0]"]


def test_claude_empty_history_with_steps_has_only_system_breakpoints():
    req = llm.build_claude_request(_prompt(history=[]), "m", steps=_steps())
    assert [w for w, _ in _breakpoints(req)] == ["system[0]", "system[1]"]


def test_claude_is_error_key_absent_when_false():
    steps = [{"text": "", "calls": [llm.ToolCall("a", "search_products", {}, "{}")],
              "results": [{"id": "a", "content": "x", "is_error": False}]}]
    block = llm.build_claude_request(_prompt(), "m", steps=steps)["messages"][-1]["content"][0]
    assert "is_error" not in block


def _one_step(text):
    return [{"text": text, "calls": [llm.ToolCall("a", "search_products", {"q": 1}, '{"q": 1}')],
             "results": [{"id": "a", "content": "x", "is_error": False}]}]


@pytest.mark.parametrize("text", ["\n\n", "  ", " \t\n", None])
def test_claude_whitespace_only_step_text_sends_no_text_block(text):
    # Anthropic rejects whitespace-only text blocks with a 400 -> the tool_use must go alone.
    msgs = llm.build_claude_request(_prompt(), "m", steps=_one_step(text))["messages"]
    assert msgs[-2] == {"role": "assistant", "content": [
        {"type": "tool_use", "id": "a", "name": "search_products", "input": {"q": 1}},
    ]}


@pytest.mark.parametrize("text", ["Let me check.", "\nLet me check.\n", "  hi  "])
def test_claude_non_empty_step_text_is_sent_unchanged(text):
    msgs = llm.build_claude_request(_prompt(), "m", steps=_one_step(text))["messages"]
    assert msgs[-2]["content"][0] == {"type": "text", "text": text}  # no strip: prefix stability
    assert msgs[-2]["content"][1]["type"] == "tool_use"


# ---------------------------------------------------------------------------
# (3) OpenAI
# ---------------------------------------------------------------------------
def test_openai_tools_conversion():
    req = llm.build_openai_request(_prompt(), "m", "s1", tools=TOOLS)
    assert req["tools"] == [
        {"type": "function", "name": "search_products", "description": "Search the catalog.",
         "parameters": TOOLS[0]["parameters"], "strict": True},
        {"type": "function", "name": "request_human", "description": "Hand over to a human.",
         "parameters": TOOLS[1]["parameters"], "strict": True},
    ]
    assert "tool_choice" not in req
    assert req["store"] is False and req["prompt_cache_key"] == "shop:s1"
    assert "previous_response_id" not in req


def test_openai_force_text_sets_tool_choice_none():
    req = llm.build_openai_request(_prompt(), "m", "s1", tools=TOOLS, force_text=True)
    assert req["tool_choice"] == "none"


def test_openai_steps_items_order_fields_and_raw_arguments():
    req = llm.build_openai_request(_prompt(), "m", "s1", tools=TOOLS, steps=_steps())
    items = req["input"]
    assert items[0]["role"] == "developer"
    assert items[3] == {"role": "user", "content": [{"type": "input_text", "text": "how much?"}]}
    assert items[4:] == [
        {"role": "assistant", "content": "Let me check."},
        {"type": "function_call", "call_id": "tu_1", "name": "search_products",
         "arguments": '{"query": "მაისური"}'},  # original string, untouched (non-ASCII not escaped)
        {"type": "function_call", "call_id": "tu_2", "name": "request_human", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "tu_1", "output": "found 2"},
        {"type": "function_call_output", "call_id": "tu_2", "output": "bad call"},
        # second step: empty text -> no assistant item; invalid raw arguments are sent back as they were
        {"type": "function_call", "call_id": "tu_3", "name": "search_products", "arguments": "{not json"},
        {"type": "function_call_output", "call_id": "tu_3", "output": "invalid arguments"},
    ]
    assert req["store"] is False


@pytest.mark.parametrize("text", ["\n\n", "  ", " \t\n", None])
def test_openai_whitespace_only_step_text_sends_no_assistant_item(text):
    items = llm.build_openai_request(_prompt(), "m", "s1", steps=_one_step(text))["input"]
    assert items[4:] == [
        {"type": "function_call", "call_id": "a", "name": "search_products", "arguments": '{"q": 1}'},
        {"type": "function_call_output", "call_id": "a", "output": "x"},
    ]


@pytest.mark.parametrize("text", ["Let me check.", "\nLet me check.\n", "  hi  "])
def test_openai_non_empty_step_text_is_sent_unchanged(text):
    items = llm.build_openai_request(_prompt(), "m", "s1", steps=_one_step(text))["input"]
    assert items[4] == {"role": "assistant", "content": text}  # no strip: prefix stability
    assert items[5]["type"] == "function_call"


# ---------------------------------------------------------------------------
# (4) parsing
# ---------------------------------------------------------------------------
def test_claude_tool_use_parsed(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _claude_response(content=[
        SimpleNamespace(type="tool_use", id="tu_9", name="search_products", input={"query": "მაისური"}),
    ]))]
    result = llm.generate(_prompt(), "s", tools=TOOLS)
    assert result.text == ""
    assert result.tool_calls == [
        llm.ToolCall("tu_9", "search_products", {"query": "მაისური"}, '{"query": "მაისური"}'),
    ]
    assert result.usage == llm.Usage(10, 5, 3, 2)


def test_claude_text_and_tool_use_together(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _claude_response(content=[
        SimpleNamespace(type="text", text="One moment. "),
        SimpleNamespace(type="tool_use", id="a", name="request_human", input={}),
        SimpleNamespace(type="text", text="Done."),
        SimpleNamespace(type="tool_use", id="b", name="search_products", input={"query": "x"}),
    ]))]
    result = llm.generate(_prompt(), "s", tools=TOOLS)
    assert result.text == "One moment. Done."
    assert [(c.id, c.name, c.arguments) for c in result.tool_calls] == [
        ("a", "request_human", {}), ("b", "search_products", {"query": "x"}),
    ]


def test_claude_non_dict_input_gives_arguments_none(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _claude_response(content=[
        SimpleNamespace(type="tool_use", id="a", name="search_products", input="oops"),
    ]))]
    call = llm.generate(_prompt(), "s", tools=TOOLS).tool_calls[0]
    assert call.arguments is None and call.raw_arguments == '"oops"'


def test_claude_refusal_has_no_tool_calls(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _claude_response(stop_reason="refusal", content=[
        SimpleNamespace(type="text", text="I cannot"),
        SimpleNamespace(type="tool_use", id="a", name="request_human", input={}),
    ]))]
    result = llm.generate(_prompt(), "s", tools=TOOLS)
    assert result.text == "" and result.tool_calls == []


def test_openai_function_call_parsed(monkeypatch):
    h = Harness(monkeypatch, "openai")
    h.script = [(0, _openai_response(text="", output=[
        SimpleNamespace(type="reasoning"),
        SimpleNamespace(type="function_call", call_id="call_1", name="search_products",
                        arguments='{"query": "მაისური"}'),
        SimpleNamespace(type="message"),
    ]))]
    result = llm.generate(_prompt(), "s", tools=TOOLS)
    assert result.text == ""
    assert result.tool_calls == [
        llm.ToolCall("call_1", "search_products", {"query": "მაისური"}, '{"query": "მაისური"}'),
    ]
    assert result.usage == llm.Usage(60, 7, 40, 0)


@pytest.mark.parametrize("raw", ["{not json", "", "[1, 2]", '"str"', "null", "42"])
def test_openai_invalid_or_non_object_arguments_give_none_and_keep_raw(monkeypatch, raw):
    h = Harness(monkeypatch, "openai")
    h.script = [(0, _openai_response(output=[
        SimpleNamespace(type="function_call", call_id="c", name="search_products", arguments=raw),
    ]))]
    call = llm.generate(_prompt(), "s", tools=TOOLS).tool_calls[0]
    assert call.arguments is None
    assert call.raw_arguments == raw


def test_no_tool_calls_gives_empty_list(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _claude_response("plain"))]
    assert llm.generate(_prompt(), "s").tool_calls == []
    h2 = Harness(monkeypatch, "openai")
    h2.script = [(0, _openai_response("plain"))]
    assert llm.generate(_prompt(), "s").tool_calls == []


def test_openai_response_without_output_attribute(monkeypatch):
    h = Harness(monkeypatch, "openai")
    resp = SimpleNamespace(output_text="hi", usage=None)
    h.script = [(0, resp)]
    result = llm.generate(_prompt(), "s")
    assert result.text == "hi" and result.tool_calls == []


def test_llm_result_positional_construction_unchanged():
    r = llm.LLMResult("t", "claude", "m", llm.Usage(1, 2, 3, 4))
    assert r.tool_calls == []
    assert llm.LLMResult("t", "claude", "m", llm.Usage()).tool_calls is not r.tool_calls  # no shared default


# ---------------------------------------------------------------------------
# (5) deadline
# ---------------------------------------------------------------------------
def test_deadline_with_less_than_min_attempt_raises_without_calling_client(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _claude_response())]
    with pytest.raises(TimeoutError, match="LLM turn budget exhausted"):
        llm.generate(_prompt(), "s", deadline=h.clock.now + 2.0)
    assert h.factory_calls == 0 and h.attempts == 0


def test_deadline_in_the_past_raises(monkeypatch):
    h = Harness(monkeypatch)
    with pytest.raises(TimeoutError):
        llm.generate(_prompt(), "s", deadline=h.clock.now - 5)
    assert h.factory_calls == 0


def test_deadline_remaining_exactly_min_attempt_is_allowed(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _claude_response("ok"))]
    assert llm.generate(_prompt(), "s", deadline=h.clock.now + 3.0).text == "ok"
    assert h.requests[0]["timeout"] == 3.0


def test_deadline_caps_request_timeout_to_remaining(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _claude_response())]
    llm.generate(_prompt(), "s", deadline=h.clock.now + 10.0)
    assert h.requests[0]["timeout"] == 10.0


def test_deadline_far_away_keeps_configured_timeout(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _claude_response())]
    llm.generate(_prompt(), "s", deadline=h.clock.now + 1000.0)
    # also bounded by the 45 s total budget, which is larger than llm_timeout_seconds here
    assert h.requests[0]["timeout"] == h.settings.llm_timeout_seconds


def test_deadline_openai_gets_timeout_too(monkeypatch):
    h = Harness(monkeypatch, "openai")
    h.script = [(0, _openai_response())]
    llm.generate(_prompt(), "s", deadline=h.clock.now + 10.0)
    assert h.requests[0]["timeout"] == 10.0


def test_transient_error_without_time_for_retry_is_not_retried(monkeypatch):
    h = Harness(monkeypatch)
    # 4 s left after the first attempt: 1.5 (delay) + 3.0 (min attempt) = 4.5 > 4 -> no retry
    h.script = [(0.0, anthropic.APITimeoutError(REQ)), (0, _claude_response())]
    with pytest.raises(anthropic.APITimeoutError):
        llm.generate(_prompt(), "s", deadline=h.clock.now + 4.0)
    assert h.attempts == 1 and h.clock.sleeps == []


def test_transient_error_with_time_for_retry_is_retried_with_remaining_timeout(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(1.0, anthropic.APITimeoutError(REQ)), (0, _claude_response("second"))]
    result = llm.generate(_prompt(), "s", deadline=h.clock.now + 10.0)
    assert result.text == "second"
    assert h.attempts == 2 and h.clock.sleeps == [1.5]
    assert h.requests[0]["timeout"] == 10.0
    assert h.requests[1]["timeout"] == pytest.approx(7.5)  # 10 - 1.0 - 1.5


def test_retry_boundary_is_inclusive(monkeypatch):
    h = Harness(monkeypatch)
    # now + 1.5 + 3.0 == deadline exactly -> allowed
    h.script = [(0.0, anthropic.APITimeoutError(REQ)), (0, _claude_response("ok"))]
    assert llm.generate(_prompt(), "s", deadline=h.clock.now + 4.5).text == "ok"
    assert h.attempts == 2


def test_deadline_beyond_total_budget_is_capped_by_total_budget(monkeypatch):
    h = Harness(monkeypatch)
    # first attempt takes 43 s of the 45 s total budget (deadline is far away): 2 s left < 4.5 -> no retry
    h.script = [(43.0, anthropic.APITimeoutError(REQ)), (0, _claude_response())]
    with pytest.raises(anthropic.APITimeoutError):
        llm.generate(_prompt(), "s", deadline=h.clock.now + 500.0)
    assert h.attempts == 1


def test_non_transient_error_with_deadline_not_retried(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _status_error(anthropic.BadRequestError, 400)), (0, _claude_response())]
    with pytest.raises(anthropic.BadRequestError):
        llm.generate(_prompt(), "s", deadline=h.clock.now + 30.0)
    assert h.attempts == 1


# ---------------------------------------------------------------------------
# (6) default path unchanged
# ---------------------------------------------------------------------------
def test_claude_default_request_identical_and_has_no_new_keys(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _claude_response())]
    llm.generate(_prompt(), "s")
    sent = h.requests[0]
    assert sent == llm.build_claude_request(_prompt(), h.settings.llm_model)
    assert json.dumps(sent) == json.dumps(llm.build_claude_request(_prompt(), h.settings.llm_model))
    assert not {"tools", "tool_choice", "timeout"} & set(sent)


def test_openai_default_request_identical_and_has_no_new_keys(monkeypatch):
    h = Harness(monkeypatch, "openai")
    h.script = [(0, _openai_response())]
    llm.generate(_prompt(), "shop-3")
    sent = h.requests[0]
    assert sent == llm.build_openai_request(_prompt(), h.settings.llm_model, "shop-3")
    assert not {"tools", "tool_choice", "timeout"} & set(sent)


def test_empty_tools_list_is_the_same_as_none():
    assert llm.build_claude_request(_prompt(), "m", tools=[]) == llm.build_claude_request(_prompt(), "m")
    assert (llm.build_openai_request(_prompt(), "m", "s", tools=[], steps=[])
            == llm.build_openai_request(_prompt(), "m", "s"))


def test_generate_with_tools_sends_them(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _claude_response())]
    llm.generate(_prompt(), "s", tools=TOOLS, steps=_steps(), force_text=True)
    sent = h.requests[0]
    assert "tools" in sent and sent["tool_choice"] == {"type": "none"} and "timeout" not in sent


def test_llm_module_imports_no_tools_or_graph_frameworks():
    import inspect

    src = inspect.getsource(llm)
    for banned in ("services.tools", "from app.services import tools", "langgraph", "langchain"):
        assert banned not in src


# ---------------------------------------------------------------------------
# (7) complete()
# ---------------------------------------------------------------------------
def test_complete_claude_request_exact(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _claude_response("summary text"))]
    result = llm.complete("SYS", "TEXT", "shop-1", max_tokens=300)
    assert h.requests == [{
        "model": h.settings.llm_model,
        "max_tokens": 300,
        "thinking": {"type": "disabled"},
        "system": [{"type": "text", "text": "SYS"}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "TEXT"}]}],
    }]
    assert result.text == "summary text" and result.provider == "claude" and result.tool_calls == []
    assert result.usage == llm.Usage(10, 5, 3, 2)


def test_complete_openai_request_exact(monkeypatch):
    h = Harness(monkeypatch, "openai")
    h.script = [(0, _openai_response("summary text"))]
    result = llm.complete("SYS", "TEXT", "shop-1", max_tokens=300)
    assert h.requests == [{
        "model": h.settings.llm_model,
        "input": [
            {"role": "developer", "content": [{"type": "input_text", "text": "SYS"}]},
            {"role": "user", "content": [{"type": "input_text", "text": "TEXT"}]},
        ],
        "max_output_tokens": 300,
        "store": False,
    }]
    assert result.text == "summary text" and result.provider == "openai"


def test_complete_provider_override(monkeypatch):
    h = Harness(monkeypatch, "claude")
    h.settings = h.settings.model_copy(update={"openai_api_key": "test-openai-key-not-real"})
    h.script = [(0, _openai_response("via openai"))]
    result = llm.complete("S", "T", "s", max_tokens=50, provider="openai")
    assert result.provider == "openai" and "input" in h.requests[0]


def test_complete_unknown_provider_raises_value_error(monkeypatch):
    h = Harness(monkeypatch)
    with pytest.raises(ValueError, match="unknown LLM provider"):
        llm.complete("S", "T", "s", max_tokens=50, provider="gemini")
    assert h.factory_calls == 0


@pytest.mark.parametrize("provider,update", [
    ("claude", {"anthropic_api_key": ""}),
    ("openai", {"openai_api_key": " "}),
])
def test_complete_not_ready_raises_runtime_error_without_factory(monkeypatch, provider, update):
    h = Harness(monkeypatch, provider)
    h.settings = h.settings.model_copy(update=update)
    with pytest.raises(RuntimeError, match="LLM key not configured"):
        llm.complete("S", "T", "s", max_tokens=50)
    assert h.factory_calls == 0


def test_complete_transient_error_retried_once(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0.1, _status_error(anthropic.RateLimitError, 429)), (0.1, _claude_response("second"))]
    assert llm.complete("S", "T", "s", max_tokens=50).text == "second"
    assert h.attempts == 2 and h.clock.sleeps == [1.5]
    assert "timeout" not in h.requests[0]


def test_complete_transient_error_twice_propagates(monkeypatch):
    h = Harness(monkeypatch)
    first, second = _status_error(anthropic.RateLimitError, 429), _status_error(anthropic.RateLimitError, 429)
    h.script = [(0.1, first), (0.1, second)]
    with pytest.raises(anthropic.RateLimitError) as info:
        llm.complete("S", "T", "s", max_tokens=50)
    assert info.value is second and h.attempts == 2


def test_complete_non_transient_not_retried(monkeypatch):
    h = Harness(monkeypatch, "openai")
    h.script = [(0, _status_error(openai.BadRequestError, 400)), (0, _openai_response())]
    with pytest.raises(openai.BadRequestError):
        llm.complete("S", "T", "s", max_tokens=50)
    assert h.attempts == 1


def test_complete_honours_deadline(monkeypatch):
    h = Harness(monkeypatch)
    h.script = [(0, _claude_response())]
    with pytest.raises(TimeoutError):
        llm.complete("S", "T", "s", max_tokens=50, deadline=h.clock.now + 1.0)
    assert h.factory_calls == 0
    llm.complete("S", "T", "s", max_tokens=50, deadline=h.clock.now + 8.0)
    assert h.requests[0]["timeout"] == 8.0


# ---------------------------------------------------------------------------
# (8) prefix stability: tools and system are byte-identical across requests
# ---------------------------------------------------------------------------
def test_claude_tools_and_system_are_byte_identical_across_calls():
    a = llm.build_claude_request(_prompt(final_text="first question"), "m", tools=TOOLS)
    b = llm.build_claude_request(_prompt(final_text="second, much longer question"), "m",
                                 tools=TOOLS, steps=_steps(), force_text=True)
    assert json.dumps(a["tools"]) == json.dumps(b["tools"])
    assert json.dumps(a["system"]) == json.dumps(b["system"])
    # history prefix (incl. its breakpoint) is identical too
    assert json.dumps(a["messages"][:2]) == json.dumps(b["messages"][:2])


def test_openai_tools_and_developer_message_are_byte_identical_across_calls():
    a = llm.build_openai_request(_prompt(final_text="first"), "m", "s", tools=TOOLS)
    b = llm.build_openai_request(_prompt(final_text="other"), "m", "s", tools=TOOLS, steps=_steps(), force_text=True)
    assert json.dumps(a["tools"]) == json.dumps(b["tools"])
    assert json.dumps(a["input"][:3]) == json.dumps(b["input"][:3])
    assert a["prompt_cache_key"] == b["prompt_cache_key"]
