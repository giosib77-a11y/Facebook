"""S11-3: Gemini call has a per-attempt timeout and a total retry budget (offline, fake clock)."""
import logging
import types as pytypes

import pytest

import app.api.webhook as webhook
import app.services.bot as bot
from tests.test_reply_delivery import PSID, SHOP_ID, _run, env  # noqa: F401  (env is a fixture)


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def _fake_settings(monkeypatch):
    settings = bot.get_settings().model_copy(update={
        "gemini_api_key": "k", "gemini_model": "m", "gemini_timeout_seconds": 20.0,
    })
    monkeypatch.setattr(bot, "get_settings", lambda: settings)


@pytest.fixture
def fake(monkeypatch):
    """Fake genai client + clock. `script` = list of (duration_s, result_or_exception)."""
    clock = FakeClock()
    monkeypatch.setattr(bot.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(bot.time, "sleep", clock.sleep)
    _fake_settings(monkeypatch)
    state = {"script": [], "client_kwargs": None, "call_timeouts": []}

    class Models:
        def generate_content(self, model, contents, config):
            ms = config.http_options.timeout
            state["call_timeouts"].append(ms)
            duration, result = state["script"].pop(0)
            clock.now += min(duration, ms / 1000)
            if isinstance(result, Exception):
                raise result
            return pytypes.SimpleNamespace(text=result)

    class Client:
        def __init__(self, **kwargs):
            state["client_kwargs"] = kwargs
            self.models = Models()

    import google.genai as genai
    monkeypatch.setattr(genai, "Client", Client)
    state["clock"] = clock
    return state


def _call():
    return bot.get_bot_reply({"name": "s", "currency": "GEL"}, [], "hi")


def test_timeout_value_passed_in_milliseconds(fake):
    fake["script"] = [(1, " ok ")]
    assert _call() == "ok"
    assert fake["client_kwargs"]["http_options"].timeout == 20000
    assert fake["call_timeouts"] == [20000]


def test_success_on_second_attempt_after_transient_error(fake):
    fake["script"] = [(1, RuntimeError("503 UNAVAILABLE")), (1, "done")]
    assert _call() == "done"
    assert fake["clock"].sleeps == [1.5]


def test_non_transient_error_not_retried(fake):
    fake["script"] = [(1, ValueError("bad request")), (1, "never")]
    with pytest.raises(ValueError):
        _call()
    assert len(fake["script"]) == 1


def test_timeouts_stop_within_budget_and_raise(fake):
    # every attempt hangs until its timeout fires
    fake["script"] = [(999, TimeoutError("Read timed out")) for _ in range(4)]
    with pytest.raises(TimeoutError):
        _call()
    elapsed = fake["clock"].now - 1000.0
    assert elapsed <= bot.GEMINI_TOTAL_BUDGET_SECONDS
    # 20s + 1.5s sleep + 20s -> remaining 3.5s: no third attempt
    assert fake["call_timeouts"] == [20000, 20000]


def test_transient_errors_budget_and_shrunk_timeout(fake):
    # each attempt burns 14s then fails with 503; the last allowed attempt gets a reduced timeout
    fake["script"] = [(14, RuntimeError("503")) for _ in range(4)]
    with pytest.raises(RuntimeError):
        _call()
    elapsed = fake["clock"].now - 1000.0
    assert elapsed <= bot.GEMINI_TOTAL_BUDGET_SECONDS
    assert all(t <= 20000 for t in fake["call_timeouts"])
    assert len(fake["call_timeouts"]) < 4 or fake["call_timeouts"][-1] < 20000


def test_attempt_timeout_capped_to_remaining_budget(fake, monkeypatch):
    monkeypatch.setattr(bot, "GEMINI_TOTAL_BUDGET_SECONDS", 12.0)
    fake["script"] = [(1, "x")]
    _call()
    assert fake["call_timeouts"] == [12000]


def test_webhook_sends_fallback_when_gemini_times_out(env, monkeypatch, caplog):  # noqa: F811
    db, sent, _ = env
    clock = FakeClock()
    monkeypatch.setattr(bot.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(bot.time, "sleep", clock.sleep)
    _fake_settings(monkeypatch)

    class Models:
        def generate_content(self, **kw):
            clock.now += kw["config"].http_options.timeout / 1000
            raise TimeoutError("Read timed out")

    class Client:
        def __init__(self, **kw):
            self.models = Models()

    import google.genai as genai
    monkeypatch.setattr(genai, "Client", Client)
    # use the real get_bot_reply (the env fixture stubbed it)
    monkeypatch.setattr(webhook, "get_bot_reply", bot.get_bot_reply)

    with caplog.at_level(logging.ERROR, logger="app"):
        _run()

    assert sent == ["ბოდიში, ამ წუთას ვერ გიპასუხებთ. სცადეთ ცოტა ხანში."]
    assert any(SHOP_ID in r.getMessage() for r in caplog.records)
    assert PSID not in "".join(r.getMessage() for r in caplog.records)


def test_config_default_timeout_is_20_seconds():
    from app.config import Settings
    assert Settings.model_fields["gemini_timeout_seconds"].default == 20.0
