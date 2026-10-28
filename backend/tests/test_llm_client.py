"""S14-4: llm.generate / client factories / bounded retry — fake SDK clients only, no network."""
import logging
from types import SimpleNamespace

import anthropic
import httpx2
import openai
import pytest

from app.services import llm
from app.services.prompt import Prompt

# conftest's autouse fixture replaces the factories with a blocker; remember the real ones.
REAL_ANTHROPIC_FACTORY = llm._anthropic_client
REAL_OPENAI_FACTORY = llm._openai_client

REQ = httpx2.Request("POST", "https://api.example.invalid/v1/x")


def _status_error(cls, status):
    return cls("boom", response=httpx2.Response(status, request=REQ), body=None)


def _prompt():
    return Prompt(layer1="L1", layer2="L2", history=[], final=[{"type": "text", "text": "hello"}])


def _claude_response(text="ok", stop_reason="end_turn", usage=None, content=None):
    return SimpleNamespace(
        content=content if content is not None else [SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=usage or SimpleNamespace(
            input_tokens=10, output_tokens=5, cache_read_input_tokens=3, cache_creation_input_tokens=2,
        ),
    )


def _openai_response(text="ok"):
    return SimpleNamespace(
        output_text=text,
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


@pytest.fixture
def h(monkeypatch):
    return Harness(monkeypatch)


# ---------------------------------------------------------------------------
# factories
# ---------------------------------------------------------------------------
def test_anthropic_factory_kwargs(monkeypatch):
    seen = {}

    class FakeAnthropic:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    s = llm.get_settings().model_copy(update={"llm_timeout_seconds": 12.5})
    REAL_ANTHROPIC_FACTORY(s)
    assert seen == {"api_key": s.anthropic_api_key, "timeout": 12.5, "max_retries": 0}


def test_openai_factory_kwargs(monkeypatch):
    seen = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    s = llm.get_settings().model_copy(update={
        "llm_provider": "openai", "openai_api_key": "test-openai-key-not-real", "llm_timeout_seconds": 7.0,
    })
    REAL_OPENAI_FACTORY(s)
    assert seen == {"api_key": "test-openai-key-not-real", "timeout": 7.0, "max_retries": 0}


def test_guard_blocks_real_clients_without_replacement():
    # conftest's autouse guard is active here: no factory replacement.
    with pytest.raises(RuntimeError, match="real LLM client blocked"):
        llm.generate(_prompt(), "shop-1")


def test_guard_blocks_openai_too(monkeypatch):
    s = llm.get_settings().model_copy(update={"llm_provider": "openai", "openai_api_key": "k"})
    monkeypatch.setattr(llm, "get_settings", lambda: s)
    with pytest.raises(RuntimeError, match="real LLM client blocked"):
        llm.generate(_prompt(), "shop-1")


# ---------------------------------------------------------------------------
# generate: success paths
# ---------------------------------------------------------------------------
def test_claude_success_text_usage_and_request(h):
    h.script = [(0.1, _claude_response("hello there"))]
    result = llm.generate(_prompt(), "shop-1")
    assert result.text == "hello there"
    assert result.provider == "claude"
    assert result.model == h.settings.claude_model
    assert result.usage == llm.Usage(10, 5, 3, 2)
    assert h.requests[0]["model"] == h.settings.claude_model
    assert "temperature" not in h.requests[0]
    assert h.attempts == 1 and h.clock.sleeps == []


def test_claude_joins_only_text_blocks_ignoring_thinking(h):
    h.script = [(0, _claude_response(content=[
        SimpleNamespace(type="thinking", thinking="secret reasoning", text="SHOULD NOT APPEAR"),
        SimpleNamespace(type="text", text="part one "),
        SimpleNamespace(type="tool_use", name="x"),
        SimpleNamespace(type="text", text="part two"),
    ]))]
    assert llm.generate(_prompt(), "s").text == "part one part two"


def test_claude_refusal_returns_empty_and_warns_with_shop(h, caplog):
    caplog.set_level(logging.WARNING)
    h.script = [(0, _claude_response("I cannot", stop_reason="refusal"))]
    result = llm.generate(_prompt(), "shop-77")
    assert result.text == ""
    assert result.usage.output_tokens == 5
    assert any("shop-77" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)


def test_claude_empty_content_gives_empty_text(h):
    h.script = [(0, _claude_response(content=[]))]
    assert llm.generate(_prompt(), "s").text == ""


def test_openai_success(monkeypatch):
    h = Harness(monkeypatch, "openai")
    h.script = [(0.1, _openai_response("hi from gpt"))]
    result = llm.generate(_prompt(), "shop-9")
    assert result.text == "hi from gpt"
    assert result.provider == "openai"
    assert result.model == h.settings.openai_model
    assert result.usage == llm.Usage(60, 7, 40, 0)
    req = h.requests[0]
    assert req["prompt_cache_key"] == "shop:shop-9" and req["store"] is False
    assert "temperature" not in req


def test_openai_none_output_text_is_empty(monkeypatch):
    h = Harness(monkeypatch, "openai")
    h.script = [(0, _openai_response(None))]
    assert llm.generate(_prompt(), "s").text == ""


# ---------------------------------------------------------------------------
# not ready
# ---------------------------------------------------------------------------
def test_not_ready_raises_without_calling_factory(monkeypatch):
    h = Harness(monkeypatch)
    h.settings = h.settings.model_copy(update={"anthropic_api_key": ""})
    with pytest.raises(RuntimeError, match="LLM key not configured: ANTHROPIC_API_KEY"):
        llm.generate(_prompt(), "s")
    assert h.factory_calls == 0


def test_not_ready_openai_names_openai_key(monkeypatch):
    h = Harness(monkeypatch, "openai")
    h.settings = h.settings.model_copy(update={"openai_api_key": " "})
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm.generate(_prompt(), "s")
    assert h.factory_calls == 0


# ---------------------------------------------------------------------------
# retry
# ---------------------------------------------------------------------------
TRANSIENT = [
    pytest.param(lambda: anthropic.APIConnectionError(request=REQ), id="anthropic-connection"),
    pytest.param(lambda: anthropic.APITimeoutError(REQ), id="anthropic-timeout"),
    pytest.param(lambda: _status_error(anthropic.RateLimitError, 429), id="anthropic-429"),
    pytest.param(lambda: _status_error(anthropic.InternalServerError, 500), id="anthropic-500"),
    pytest.param(lambda: _status_error(anthropic.OverloadedError, 529), id="anthropic-529"),
    pytest.param(lambda: _status_error(anthropic.APIStatusError, 503), id="anthropic-generic-503"),
    pytest.param(lambda: openai.APIConnectionError(request=REQ), id="openai-connection"),
    pytest.param(lambda: openai.APITimeoutError(REQ), id="openai-timeout"),
    pytest.param(lambda: _status_error(openai.RateLimitError, 429), id="openai-429"),
    pytest.param(lambda: _status_error(openai.InternalServerError, 502), id="openai-502"),
    pytest.param(lambda: _status_error(openai.APIStatusError, 503), id="openai-generic-503"),
]


@pytest.mark.parametrize("make_exc", TRANSIENT)
def test_transient_error_is_retried_once_then_succeeds(h, make_exc):
    h.script = [(0.2, make_exc()), (0.3, _claude_response("second try"))]
    result = llm.generate(_prompt(), "s")
    assert result.text == "second try"
    assert h.attempts == 2
    assert h.clock.sleeps == [1.5]


@pytest.mark.parametrize("make_exc", TRANSIENT)
def test_transient_error_twice_propagates_after_exactly_two_attempts(h, make_exc):
    first, second = make_exc(), make_exc()
    h.script = [(0.2, first), (0.2, second)]
    with pytest.raises(type(second)) as info:
        llm.generate(_prompt(), "s")
    assert info.value is second
    assert h.attempts == 2
    assert h.clock.sleeps == [1.5]


@pytest.mark.parametrize("make_exc", [
    pytest.param(lambda: _status_error(anthropic.BadRequestError, 400), id="anthropic-400"),
    pytest.param(lambda: _status_error(anthropic.AuthenticationError, 401), id="anthropic-401"),
    pytest.param(lambda: _status_error(anthropic.NotFoundError, 404), id="anthropic-404"),
    pytest.param(lambda: _status_error(openai.BadRequestError, 400), id="openai-400"),
    pytest.param(lambda: _status_error(openai.APIStatusError, 413), id="openai-generic-413"),
    pytest.param(lambda: ValueError("not an SDK error"), id="plain-exception"),
])
def test_non_transient_error_is_not_retried(h, make_exc):
    h.script = [(0.1, make_exc())]
    with pytest.raises(Exception):
        llm.generate(_prompt(), "s")
    assert h.attempts == 1
    assert h.clock.sleeps == []


def test_no_retry_when_budget_exhausted(h):
    # first attempt "takes" 30 s: 30 + 1.5 + 20 > 45
    h.script = [(30.0, anthropic.APITimeoutError(REQ)), (0.1, _claude_response())]
    with pytest.raises(anthropic.APITimeoutError):
        llm.generate(_prompt(), "s")
    assert h.attempts == 1
    assert h.clock.sleeps == []


def test_retry_allowed_exactly_at_budget_boundary(h):
    # 23.5 + 1.5 + 20 == 45.0 -> allowed (<=)
    h.script = [(23.5, anthropic.APITimeoutError(REQ)), (0.1, _claude_response("late ok"))]
    assert llm.generate(_prompt(), "s").text == "late ok"
    assert h.attempts == 2


def test_budget_uses_configured_timeout(h):
    h.settings = h.settings.model_copy(update={"llm_timeout_seconds": 5.0})
    # 38 + 1.5 + 5 = 44.5 <= 45 -> retry; with the default 20 s it would be refused
    h.script = [(38.0, anthropic.APITimeoutError(REQ)), (0.1, _claude_response("ok"))]
    assert llm.generate(_prompt(), "s").text == "ok"


def test_retry_logs_warning_with_shop_and_error_type(h, caplog):
    caplog.set_level(logging.WARNING)
    h.script = [(0, anthropic.APITimeoutError(REQ)), (0, _claude_response())]
    llm.generate(_prompt(), "shop-5")
    msgs = [r.getMessage() for r in caplog.records]
    assert any("shop-5" in m and "APITimeoutError" in m for m in msgs)


def test_openai_transient_retry(monkeypatch):
    h = Harness(monkeypatch, "openai")
    h.script = [(0.1, _status_error(openai.RateLimitError, 429)), (0.1, _openai_response("ok"))]
    assert llm.generate(_prompt(), "s").text == "ok"
    assert h.attempts == 2 and h.clock.sleeps == [1.5]


def test_openai_400_not_retried(monkeypatch):
    h = Harness(monkeypatch, "openai")
    h.script = [(0.1, _status_error(openai.BadRequestError, 400))]
    with pytest.raises(openai.BadRequestError):
        llm.generate(_prompt(), "s")
    assert h.attempts == 1


# ---------------------------------------------------------------------------
# generate(provider=...) override (Stage 15 comparison script)
# ---------------------------------------------------------------------------
OPENAI_TEST_KEY = "test-openai-key-not-real"


class OverrideHarness(Harness):
    """Harness with BOTH keys set and a separate counting factory per provider."""

    def __init__(self, monkeypatch, default_provider, openai_key=OPENAI_TEST_KEY):
        super().__init__(monkeypatch, default_provider)
        self.settings = self.settings.model_copy(update={"openai_api_key": openai_key})
        self.original_provider = default_provider
        self.claude_factory_settings = []
        self.openai_factory_settings = []
        fake_client = SimpleNamespace(
            messages=SimpleNamespace(create=self._create),
            responses=SimpleNamespace(create=self._create),
        )

        def claude_factory(s):
            self.claude_factory_settings.append(s)
            return fake_client

        def openai_factory(s):
            self.openai_factory_settings.append(s)
            return fake_client

        monkeypatch.setattr(llm, "_anthropic_client", claude_factory)
        monkeypatch.setattr(llm, "_openai_client", openai_factory)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        duration, result = self.script.pop(0)
        self.clock.now += duration
        if isinstance(result, Exception):
            raise result
        return result


def test_override_openai_over_claude_default(monkeypatch):
    h = OverrideHarness(monkeypatch, "claude")
    h.script = [(0.1, _openai_response("from gpt"))]
    result = llm.generate(_prompt(), "shop-1", provider="openai")
    assert result.text == "from gpt"
    assert result.provider == "openai"
    assert result.model == "gpt-6-luna"
    assert h.attempts == 1
    assert h.requests[0]["model"] == "gpt-6-luna"
    assert "input" in h.requests[0]  # Responses API request shape, not Claude's "messages"
    assert len(h.openai_factory_settings) == 1 and len(h.claude_factory_settings) == 0
    assert h.openai_factory_settings[0].openai_api_key == OPENAI_TEST_KEY


def test_override_claude_over_openai_default(monkeypatch):
    h = OverrideHarness(monkeypatch, "openai")
    h.script = [(0.1, _claude_response("from claude"))]
    result = llm.generate(_prompt(), "shop-1", provider="claude")
    assert result.text == "from claude"
    assert result.provider == "claude"
    assert result.model == "claude-haiku-5-5"
    assert h.attempts == 1
    assert h.requests[0]["model"] == "claude-haiku-5-5"
    assert "messages" in h.requests[0]
    assert len(h.claude_factory_settings) == 1 and len(h.openai_factory_settings) == 0
    assert h.claude_factory_settings[0].anthropic_api_key == h.settings.anthropic_api_key


@pytest.mark.parametrize("bad", ["gemini", "", "Claude", "OPENAI", " openai"])
def test_override_unknown_provider_raises_value_error(monkeypatch, bad):
    h = OverrideHarness(monkeypatch, "claude")
    with pytest.raises(ValueError, match="unknown LLM provider"):
        llm.generate(_prompt(), "s", provider=bad)
    assert h.claude_factory_settings == [] and h.openai_factory_settings == []
    assert h.attempts == 0


def test_override_provider_without_key_raises_with_its_env_name(monkeypatch):
    h = OverrideHarness(monkeypatch, "claude", openai_key="")  # default claude is ready
    assert h.settings.llm_ready
    with pytest.raises(RuntimeError, match="LLM key not configured: OPENAI_API_KEY"):
        llm.generate(_prompt(), "s", provider="openai")
    assert h.claude_factory_settings == [] and h.openai_factory_settings == []
    assert h.attempts == 0


def test_explicit_none_provider_uses_default(monkeypatch):
    h = OverrideHarness(monkeypatch, "openai")
    h.script = [(0.1, _openai_response("default path"))]
    result = llm.generate(_prompt(), "s", provider=None)
    assert result.provider == "openai" and result.text == "default path"
    assert len(h.openai_factory_settings) == 1 and len(h.claude_factory_settings) == 0


def test_override_does_not_mutate_cached_settings(monkeypatch):
    h = OverrideHarness(monkeypatch, "claude")
    h.script = [(0.1, _openai_response("x"))]
    llm.generate(_prompt(), "s", provider="openai")
    assert llm.get_settings() is h.settings
    assert llm.get_settings().llm_provider == h.original_provider == "claude"
    # the factory got a copy with the override, not the original object
    assert h.openai_factory_settings[0] is not h.settings
    assert h.openai_factory_settings[0].llm_provider == "openai"


def test_override_path_retries_transient_error_once(monkeypatch):
    h = OverrideHarness(monkeypatch, "claude")
    h.script = [(0.1, _status_error(openai.RateLimitError, 429)), (0.1, _openai_response("second"))]
    result = llm.generate(_prompt(), "s", provider="openai")
    assert result.text == "second" and result.provider == "openai"
    assert h.attempts == 2
    assert h.clock.sleeps == [1.5]
    assert len(h.claude_factory_settings) == 0
