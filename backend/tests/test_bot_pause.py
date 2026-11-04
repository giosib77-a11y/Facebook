"""S20-3 (A-035): handoff / seller-echo pause of the bot in the webhook.

* handoff turn  -> upsert carries `bot_paused_until` (= now + BOT_PAUSE_HOURS)
* seller's manual reply (`message.is_echo`, app_id != FB_APP_ID) -> stored as role "operator" + pause
* paused conversation -> customer message stored, no LLM / send / photo download / track_bot_customer
* without migration 0033 -> pause disabled, text still stored, one WARNING per process

`_process_events` is called directly with a fake service client; nothing leaves the process.
"""
import logging
from datetime import datetime, timedelta, timezone

import pytest

import app.api.webhook as webhook
from app.services import facebook
from app.services.graph import TurnResult
from tests.conftest import FakeQuery, FakeSupabase
from tests.test_reply_delivery import PAGE_ID, PSID, SHOP_ID

CUSTOMER_TEXT = "ფასი რა არის? ჩემი ნომერია 555123456"
ECHO_TEXT = "10% ფასდაკლება"
OUR_APP_ID = "111"
SELLER_APP_ID = "999"

PAUSE_WARNING = "bot_conversations.bot_paused_until missing"
APP_ID_WARNING = "FB_APP_ID not set"


@pytest.fixture(autouse=True)
def _reset_process_state(monkeypatch):
    """Module-level one-shot flags and the duplicate-mid memory are process-global."""
    monkeypatch.setattr(webhook, "_PAUSE_COLUMN_WARNED", False, raising=False)
    monkeypatch.setattr(webhook, "_ECHO_APP_ID_WARNED", False, raising=False)
    webhook._SEEN_MIDS.clear()
    yield
    webhook._SEEN_MIDS.clear()


def _make_env(monkeypatch, db):
    db.responses[("shops", "select")] = [{
        "id": SHOP_ID, "bot_enabled": True, "facebook_page_token": "enc",
        "subscription_tier": "free",
    }]
    db.responses[("products", "select")] = []
    db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 1}]

    calls = {"bot": 0, "download": 0}
    sent = []

    def fake_run_turn(shop, products, text, history, images=None, **kw):
        calls["bot"] += 1
        return calls.get("result") or TurnResult("llm reply")

    def fake_download(url, timeout=8):
        calls["download"] += 1
        return b"img", "image/jpeg"

    monkeypatch.setattr(webhook, "get_service_client", lambda: db)
    monkeypatch.setattr(webhook, "decrypt", lambda token: "page-token")
    monkeypatch.setattr(webhook, "send_text_message", lambda tok, psid, text: sent.append(text))
    monkeypatch.setattr(webhook, "download_image", fake_download)
    monkeypatch.setattr(webhook, "run_turn", fake_run_turn)
    _settings(monkeypatch, fb_app_id=OUR_APP_ID)
    return db, sent, calls


@pytest.fixture
def env(monkeypatch, service_db):
    return _make_env(monkeypatch, service_db)


def _settings(monkeypatch, **update):
    s = webhook.get_settings().model_copy(update=update)
    monkeypatch.setattr(webhook, "get_settings", lambda: s)
    return s


def _customer(message=None):
    webhook._process_events({"object": "page", "entry": [{
        "id": PAGE_ID,
        "messaging": [{"sender": {"id": PSID}, "message": message or {"text": CUSTOMER_TEXT}}],
    }]})


def _echo(*messages, recipient=PSID):
    """Seller's reply as Meta delivers it: sender = the page, recipient = the customer."""
    events = []
    for m in messages:
        events.append({
            "sender": {"id": PAGE_ID}, "recipient": {"id": recipient},
            "message": {"is_echo": True, **m},
        })
    webhook._process_events({"object": "page", "entry": [{"id": PAGE_ID, "messaging": events}]})


def _warnings(caplog, needle):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and needle in r.getMessage()]


def _paused_row(until: datetime, messages=None) -> dict:
    return {
        "bot_paused_until": until.isoformat(),
        "messages": messages or [{"role": "user", "content": "hi"}, {"role": "bot", "content": "hello"}],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "summary": None,
    }


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ---------------------------------------------------------------- handoff pause

def test_handoff_turn_sets_bot_paused_until_twelve_hours_ahead(env):
    db, sent, calls = env
    calls["result"] = TurnResult("ოპერატორი დაგიკავშირდებათ", handoff=True)

    before = datetime.now(timezone.utc)
    _customer()

    (save,) = db.calls_for("bot_conversations", "upsert")
    assert save.payload["needs_attention"] is True
    until = _parse(save.payload["bot_paused_until"])
    assert abs((until - (before + timedelta(hours=webhook.BOT_PAUSE_HOURS))).total_seconds()) < 120
    assert webhook.BOT_PAUSE_HOURS == 12


def test_normal_turn_does_not_pause(env):
    db, sent, calls = env

    _customer()

    (save,) = db.calls_for("bot_conversations", "upsert")
    assert "bot_paused_until" not in save.payload
    assert "needs_attention" not in save.payload


def test_over_limit_operator_reply_also_pauses(env, monkeypatch):
    db, sent, calls = env
    _settings(monkeypatch, anthropic_api_key="")  # bot disabled -> operator reply + needs_attention

    _customer()

    (save,) = db.calls_for("bot_conversations", "upsert")
    assert save.payload["needs_attention"] is True
    assert "bot_paused_until" in save.payload
    assert calls["bot"] == 0


# ---------------------------------------------------------------- paused conversation

def test_paused_conversation_stores_message_without_reply(env, caplog):
    db, sent, calls = env
    prev = [{"role": "user", "content": "hi"}, {"role": "operator", "content": "მოგესალმებით"}]
    db.responses[("bot_conversations", "select")] = [
        _paused_row(datetime.now(timezone.utc) + timedelta(hours=3), prev)
    ]

    with caplog.at_level(logging.INFO, logger="app"):
        _customer()

    assert calls == {"bot": 0, "download": 0}
    assert sent == []
    assert db.rpc_calls == []  # track_bot_customer is not called
    assert db.calls_for("llm_usage", "insert") == []
    (save,) = db.calls_for("bot_conversations", "upsert")
    assert save.payload["messages"] == prev + [{"role": "user", "content": CUSTOMER_TEXT}]
    # pause is not extended by the customer, and handoff flags are untouched
    assert "bot_paused_until" not in save.payload
    assert "needs_attention" not in save.payload
    assert "attention_at" not in save.payload
    assert any("bot paused - message stored without reply" in r.getMessage() for r in caplog.records)


def test_paused_conversation_photo_is_not_downloaded(env):
    db, sent, calls = env
    db.responses[("bot_conversations", "select")] = [_paused_row(datetime.now(timezone.utc) + timedelta(hours=1))]

    _customer({"attachments": [{"type": "image", "payload": {"url": "https://cdn.example.com/a.jpg"}}]})

    assert calls == {"bot": 0, "download": 0}
    assert sent == []
    (save,) = db.calls_for("bot_conversations", "upsert")
    assert save.payload["messages"][-1] == {"role": "user", "content": "[სურათი]"}


def test_paused_until_with_z_suffix_is_understood(env):
    db, sent, calls = env
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.responses[("bot_conversations", "select")] = [{"bot_paused_until": future, "messages": []}]

    _customer()

    assert calls["bot"] == 0 and sent == []


def test_expired_pause_runs_the_normal_path(env):
    db, sent, calls = env
    db.responses[("bot_conversations", "select")] = [_paused_row(datetime.now(timezone.utc) - timedelta(minutes=1))]

    _customer()

    assert calls["bot"] == 1
    assert sent == ["llm reply"]
    assert [c.fn for c in db.rpc_calls] == ["track_bot_customer"]


def test_garbage_paused_until_is_treated_as_not_paused(env):
    db, sent, calls = env
    db.responses[("bot_conversations", "select")] = [{"bot_paused_until": "not-a-date", "messages": []}]

    _customer()

    assert calls["bot"] == 1 and sent == ["llm reply"]


# ---------------------------------------------------------------- seller's echo

def test_seller_echo_is_stored_as_operator_and_pauses(env):
    db, sent, calls = env
    db.responses[("bot_conversations", "select")] = [{
        "messages": [{"role": "user", "content": "hi"}, {"role": "bot", "content": "hello"}],
        "updated_at": datetime.now(timezone.utc).isoformat(), "summary": None,
    }]

    before = datetime.now(timezone.utc)
    _echo({"mid": "m-echo-1", "app_id": SELLER_APP_ID, "text": ECHO_TEXT})

    (save,) = db.calls_for("bot_conversations", "upsert")
    assert save.payload["psid"] == PSID  # recipient, not the page
    assert save.payload["shop_id"] == SHOP_ID
    assert save.payload["messages"][-1] == {"role": "operator", "content": ECHO_TEXT}
    assert save.payload["messages"][:2] == [{"role": "user", "content": "hi"}, {"role": "bot", "content": "hello"}]
    until = _parse(save.payload["bot_paused_until"])
    assert abs((until - (before + timedelta(hours=12))).total_seconds()) < 120
    assert "needs_attention" not in save.payload and "attention_at" not in save.payload
    assert sent == [] and calls == {"bot": 0, "download": 0}
    assert db.rpc_calls == []


def test_seller_echo_without_app_id_counts_as_seller(env):
    db, sent, calls = env  # e.g. a reply typed directly in Messenger / Business Suite may carry no app_id

    _echo({"mid": "m-echo-noapp", "text": ECHO_TEXT})

    (save,) = db.calls_for("bot_conversations", "upsert")
    assert save.payload["messages"][-1]["role"] == "operator"


@pytest.mark.parametrize("app_id", [OUR_APP_ID, int(OUR_APP_ID)])
def test_own_app_echo_is_ignored(env, app_id):
    db, sent, calls = env

    _echo({"mid": f"m-own-{app_id!r}", "app_id": app_id, "text": "llm reply"})

    assert db.calls_for("bot_conversations", "upsert") == []
    assert db.calls_for("bot_conversations", "select") == []


def test_empty_fb_app_id_ignores_echoes_with_one_warning(env, monkeypatch, caplog):
    db, sent, calls = env
    _settings(monkeypatch, fb_app_id="")

    with caplog.at_level(logging.WARNING, logger="app"):
        _echo({"mid": "m-a", "app_id": SELLER_APP_ID, "text": ECHO_TEXT})
        _echo({"mid": "m-b", "app_id": SELLER_APP_ID, "text": ECHO_TEXT})

    assert db.calls_for("bot_conversations", "upsert") == []
    assert len(_warnings(caplog, APP_ID_WARNING)) == 1


def test_echo_without_text_is_stored_as_attachment_marker(env):
    db, sent, calls = env

    _echo({"mid": "m-att", "app_id": SELLER_APP_ID, "attachments": [{"type": "image"}]})

    (save,) = db.calls_for("bot_conversations", "upsert")
    assert save.payload["messages"][-1] == {"role": "operator", "content": "[დანართი]"}


def test_long_echo_text_is_truncated(env):
    db, sent, calls = env

    _echo({"mid": "m-long", "app_id": SELLER_APP_ID, "text": "ა" * 5000})

    (save,) = db.calls_for("bot_conversations", "upsert")
    assert len(save.payload["messages"][-1]["content"]) == 2000


def test_echo_without_recipient_is_ignored(env):
    db, sent, calls = env

    webhook._process_events({"object": "page", "entry": [{"id": PAGE_ID, "messaging": [{
        "sender": {"id": PAGE_ID}, "message": {"is_echo": True, "mid": "m-norcpt", "app_id": SELLER_APP_ID, "text": "x"},
    }]}]})

    assert db.calls_for("bot_conversations", "upsert") == []


def test_duplicate_echo_mid_is_handled_once(env):
    db, sent, calls = env

    _echo({"mid": "m-dup", "app_id": SELLER_APP_ID, "text": ECHO_TEXT})
    _echo({"mid": "m-dup", "app_id": SELLER_APP_ID, "text": ECHO_TEXT})

    assert len(db.calls_for("bot_conversations", "upsert")) == 1


def test_echo_with_memory_disabled_still_pauses_without_messages(env, monkeypatch):
    db, sent, calls = env
    _settings(monkeypatch, bot_memory_messages=0)

    _echo({"mid": "m-nomem", "app_id": SELLER_APP_ID, "text": ECHO_TEXT})

    (save,) = db.calls_for("bot_conversations", "upsert")
    assert "messages" not in save.payload
    assert "bot_paused_until" in save.payload


def test_echo_storage_failure_does_not_break_the_batch(env, caplog):
    db, sent, calls = env
    db.errors[("bot_conversations", "upsert")] = RuntimeError("db down")

    with caplog.at_level(logging.WARNING, logger="app"):
        webhook._process_events({"object": "page", "entry": [{"id": PAGE_ID, "messaging": [
            {"sender": {"id": PAGE_ID}, "recipient": {"id": PSID},
             "message": {"is_echo": True, "mid": "m-fail", "app_id": SELLER_APP_ID, "text": ECHO_TEXT}},
        ]}]})

    assert any("საუბრის შენახვა ვერ მოხერხდა" in r.getMessage() for r in caplog.records)
    assert PSID not in "\n".join(r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- without migration 0033

class _NoPauseColumnQuery(FakeQuery):
    """Postgres without migration 0033: any statement naming `bot_paused_until` fails."""

    def select(self, *columns, **kwargs):
        self._columns = columns
        return super().select(*columns, **kwargs)

    def execute(self):
        names_column = (
            self.op == "upsert" and "bot_paused_until" in (self.payload or {})
        ) or (
            self.op == "select" and any("bot_paused_until" in str(c) for c in getattr(self, "_columns", ()))
        )
        if names_column:
            self._db.rejected.append(self)
            raise RuntimeError("column bot_paused_until does not exist")
        return super().execute()


class _NoPauseColumnDb(FakeSupabase):
    def __init__(self):
        super().__init__()
        self.rejected: list[FakeQuery] = []

    def table(self, name):
        return _NoPauseColumnQuery(self, name)


def test_handoff_without_migration_0033_falls_back_and_warns_once(monkeypatch, caplog):
    db, sent, calls = _make_env(monkeypatch, _NoPauseColumnDb())
    calls["result"] = TurnResult("ოპერატორი დაგიკავშირდებათ", handoff=True)

    with caplog.at_level(logging.WARNING, logger="app"):
        _customer()
        webhook._SEEN_MIDS.clear()
        webhook._RATE_HITS.clear()
        _customer()

    upserts = db.calls_for("bot_conversations", "upsert")
    assert len(upserts) == 2
    for save in upserts:
        assert save.payload["needs_attention"] is True
        assert "bot_paused_until" not in save.payload
        assert save.payload["messages"][-1] == {"role": "bot", "content": "ოპერატორი დაგიკავშირდებათ"}
    assert any("bot_paused_until" in (r.payload or {}) for r in db.rejected if r.op == "upsert")
    assert len(_warnings(caplog, PAUSE_WARNING)) == 1
    assert sent == ["ოპერატორი დაგიკავშირდებათ"] * 2


def test_echo_without_migration_0033_still_stores_the_text(monkeypatch, caplog):
    db, sent, calls = _make_env(monkeypatch, _NoPauseColumnDb())

    with caplog.at_level(logging.WARNING, logger="app"):
        _echo({"mid": "m-nm1", "app_id": SELLER_APP_ID, "text": ECHO_TEXT})
        _echo({"mid": "m-nm2", "app_id": SELLER_APP_ID, "text": ECHO_TEXT})

    upserts = db.calls_for("bot_conversations", "upsert")
    assert len(upserts) == 2
    for save in upserts:
        assert save.payload["messages"][-1] == {"role": "operator", "content": ECHO_TEXT}
        assert "bot_paused_until" not in save.payload
    assert len(_warnings(caplog, PAUSE_WARNING)) == 1


def test_select_failure_means_not_paused(env):
    db, sent, calls = env
    db.errors[("bot_conversations", "select")] = RuntimeError("column does not exist")

    _customer()

    assert calls["bot"] == 1
    assert sent == ["llm reply"]


# ---------------------------------------------------------------- logs

def test_logs_contain_no_psid_or_message_text(env, caplog):
    db, sent, calls = env

    with caplog.at_level(logging.DEBUG, logger="app"):
        _echo({"mid": "m-log", "app_id": SELLER_APP_ID, "text": ECHO_TEXT})
        db.responses[("bot_conversations", "select")] = [
            _paused_row(datetime.now(timezone.utc) + timedelta(hours=2))
        ]
        _customer()

    messages = "\n".join(r.getMessage() for r in caplog.records)
    assert "seller reply - bot paused" in messages
    assert "bot paused - message stored without reply" in messages
    assert PSID not in messages
    assert ECHO_TEXT not in messages
    assert "555123456" not in messages
    assert CUSTOMER_TEXT not in messages


# ---------------------------------------------------------------- subscribe_page

def test_subscribe_page_requests_message_echoes(monkeypatch):
    captured = {}

    def fake_graph(method, path, **kw):
        captured.update(method=method, path=path, **kw)

    monkeypatch.setattr(facebook, "_graph", fake_graph)

    facebook.subscribe_page("123", "page-token")

    assert captured["method"] == "POST"
    assert captured["path"] == "/123/subscribed_apps"
    fields = captured["params"]["subscribed_fields"].split(",")
    assert "message_echoes" in fields
    assert "messages" in fields and "messaging_postbacks" in fields
