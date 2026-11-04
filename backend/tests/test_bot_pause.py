"""S20-3 (A-035): handoff / seller-echo pause of the bot in the webhook.

* handoff turn  -> upsert carries `bot_paused_until` (= now + BOT_PAUSE_HOURS)
* seller's manual reply (`message.is_echo`, app_id != FB_APP_ID) -> stored as role "operator" + pause
* paused conversation -> customer message stored, no LLM / send / photo download / track_bot_customer
* without migration 0033 -> pause disabled, text still stored, one WARNING per process
* S20-20: our own echo is recognised by the Send API `message_id`; an Instagram echo without app_id never pauses

`_process_events` is called directly with a fake service client; nothing leaves the process.
"""
import logging
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import httpx
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
    monkeypatch.setattr(webhook, "_OUR_MIDS", OrderedDict(), raising=False)  # S20-20: fresh per test
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


def _echo(*messages, recipient=PSID, obj="page"):
    """Seller's reply as Meta delivers it: sender = the page, recipient = the customer."""
    events = []
    for m in messages:
        events.append({
            "sender": {"id": PAGE_ID}, "recipient": {"id": recipient},
            "message": {"is_echo": True, **m},
        })
    webhook._process_events({"object": obj, "entry": [{"id": PAGE_ID, "messaging": events}]})


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
    assert [c.fn for c in db.rpc_calls if c.fn == "track_bot_customer"] == ["track_bot_customer"]


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


# ---------------------------------------------------------------- S20-20: own echo by sent message_id

def _send_with_ids(monkeypatch, sent, fail_on=None):
    """Fake Send API: every call returns its own message_id; call number `fail_on` raises GraphError."""
    n = {"i": 0}

    def fake(tok, psid, text):
        n["i"] += 1
        if fail_on == n["i"]:
            raise facebook.GraphError(500, "send failed")
        sent.append(text)
        return [f"m_sent_{n['i']}"]

    monkeypatch.setattr(webhook, "send_text_message", fake)


def _only_the_turn_was_saved(db):
    """The bot's own turn is the single upsert; no operator message and no pause was written."""
    (save,) = db.calls_for("bot_conversations", "upsert")
    assert "bot_paused_until" not in save.payload
    assert all(m["role"] != "operator" for m in save.payload["messages"])


def test_echo_of_a_sent_message_id_without_app_id_does_not_pause(env, monkeypatch):
    db, sent, calls = env
    _send_with_ids(monkeypatch, sent)

    _customer()
    assert sent == ["llm reply"]
    _echo({"mid": "m_sent_1", "text": "llm reply"})  # no app_id (e.g. Instagram)

    _only_the_turn_was_saved(db)


def test_echo_of_every_chunk_of_a_split_reply_is_ours(env, monkeypatch):
    db, sent, calls = env
    _send_with_ids(monkeypatch, sent)
    calls["result"] = TurnResult("ა" * 1000 + ". " + "ბ" * 1000)

    _customer()
    assert len(sent) == 2
    _echo({"mid": "m_sent_1", "text": "x"}, {"mid": "m_sent_2", "text": "y"})

    _only_the_turn_was_saved(db)


def test_echo_of_the_operator_soon_reply_is_ours(env, monkeypatch):
    db, sent, calls = env
    _send_with_ids(monkeypatch, sent)
    monkeypatch.setattr(webhook.budget, "blocked_reason", lambda sc, shop: "kill_switch")

    _customer()
    assert sent == [webhook.OPERATOR_SOON_REPLY] and calls["bot"] == 0
    (before,) = db.calls_for("bot_conversations", "upsert")
    _echo({"mid": "m_sent_1", "text": webhook.OPERATOR_SOON_REPLY})

    assert len(db.calls_for("bot_conversations", "upsert")) == 1  # the echo wrote nothing
    assert before.payload["needs_attention"] is True


def test_failed_chunk_is_not_remembered_but_the_delivered_one_is(env, monkeypatch):
    db, sent, calls = env
    _send_with_ids(monkeypatch, sent, fail_on=2)
    calls["result"] = TurnResult("ა" * 1000 + ". " + "ბ" * 1000)

    _customer()

    assert list(webhook._OUR_MIDS) == ["m_sent_1"]


def test_send_returning_none_or_junk_is_tolerated(env, monkeypatch):
    db, sent, calls = env  # the default fake returns None (old send_text_message contract)
    monkeypatch.setattr(webhook, "send_text_message", lambda tok, psid, text: sent.append(text) or [None, "", 7])

    _customer()

    assert sent == ["llm reply"] and list(webhook._OUR_MIDS) == []


def test_instagram_echo_without_app_id_and_unknown_mid_does_not_pause(env, caplog):
    db, sent, calls = env

    with caplog.at_level(logging.INFO, logger="app"):
        _echo({"mid": "m-ig-1", "text": ECHO_TEXT}, obj="instagram")

    assert db.calls_for("bot_conversations", "upsert") == []
    assert any("instagram echo without app_id ignored" in r.getMessage() for r in caplog.records)


def test_instagram_echo_with_a_foreign_app_id_is_still_the_sellers(env):
    db, sent, calls = env

    _echo({"mid": "m-ig-2", "app_id": SELLER_APP_ID, "text": ECHO_TEXT}, obj="instagram")

    (save,) = db.calls_for("bot_conversations", "upsert")
    assert save.payload["messages"][-1] == {"role": "operator", "content": ECHO_TEXT}
    assert "bot_paused_until" in save.payload


def test_page_echo_with_a_foreign_app_id_and_unknown_mid_is_the_sellers(env):
    db, sent, calls = env
    webhook._remember_our_mids(["m_something_else"])

    _echo({"mid": "m-page-9", "app_id": SELLER_APP_ID, "text": ECHO_TEXT}, obj="page")

    (save,) = db.calls_for("bot_conversations", "upsert")
    assert save.payload["messages"][-1]["role"] == "operator"
    assert "bot_paused_until" in save.payload


def test_sent_message_id_expires_after_ttl(env):
    db, sent, calls = env
    webhook._OUR_MIDS["m-old"] = time.monotonic() - webhook._OUR_TTL - 1
    webhook._remember_our_mids(["m-fresh"])

    _echo({"mid": "m-fresh", "app_id": SELLER_APP_ID, "text": ECHO_TEXT})
    assert db.calls_for("bot_conversations", "upsert") == []  # still ours

    _echo({"mid": "m-old", "app_id": SELLER_APP_ID, "text": ECHO_TEXT})
    (save,) = db.calls_for("bot_conversations", "upsert")  # forgotten -> seller's
    assert save.payload["messages"][-1]["role"] == "operator"
    assert "m-old" not in webhook._OUR_MIDS


def test_sent_message_ids_are_capped(monkeypatch):
    monkeypatch.setattr(webhook, "_OUR_MAX", 3)

    webhook._remember_our_mids([f"m{i}" for i in range(5)])

    assert list(webhook._OUR_MIDS) == ["m2", "m3", "m4"]


def test_own_mid_is_recognised_even_when_fb_app_id_is_empty(env, monkeypatch, caplog):
    db, sent, calls = env
    _settings(monkeypatch, fb_app_id="")
    webhook._remember_our_mids(["m-mine"])

    with caplog.at_level(logging.WARNING, logger="app"):
        _echo({"mid": "m-mine", "text": "llm reply"})

    assert db.calls_for("bot_conversations", "upsert") == []
    assert _warnings(caplog, APP_ID_WARNING) == []  # recognised before the app_id rule


def test_every_echo_logs_its_app_id_without_psid_or_text(env, caplog):
    db, sent, calls = env

    with caplog.at_level(logging.DEBUG, logger="app"):
        _echo({"mid": "m-l1", "app_id": SELLER_APP_ID, "text": ECHO_TEXT})
        _echo({"mid": "m-l2", "text": ECHO_TEXT}, obj="instagram")

    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert f"echo app_id={SELLER_APP_ID} (shop={SHOP_ID})" in infos
    assert f"echo app_id=none (shop={SHOP_ID})" in infos
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert PSID not in joined and ECHO_TEXT not in joined


def test_echo_failure_warning_has_class_name_but_no_traceback(env, monkeypatch, caplog):
    db, sent, calls = env

    def boom(*a, **kw):
        raise RuntimeError(f"db error for {PSID}")

    monkeypatch.setattr(webhook, "_handle_echo", boom)

    with caplog.at_level(logging.WARNING, logger="app"):
        _echo({"mid": "m-boom", "app_id": SELLER_APP_ID, "text": ECHO_TEXT})

    (rec,) = [r for r in caplog.records if "echo-ს დამუშავება ვერ მოხერხდა" in r.getMessage()]
    assert "RuntimeError" in rec.getMessage()
    assert rec.exc_info is None
    assert PSID not in rec.getMessage()


def _fake_graph_returning(monkeypatch, response):
    captured = {}

    def fake_graph(method, path, **kw):
        captured.update(method=method, path=path, **kw)
        return response

    monkeypatch.setattr(facebook, "_graph", fake_graph)
    return captured


def test_send_text_message_returns_the_message_id(monkeypatch):
    captured = _fake_graph_returning(
        monkeypatch, httpx.Response(200, json={"recipient_id": PSID, "message_id": "m_1"}),
    )

    assert facebook.send_text_message("page-token", PSID, "hello") == ["m_1"]
    assert captured["path"] == "/me/messages"
    assert captured["json"]["message"] == {"text": "hello"}


@pytest.mark.parametrize("response", [
    httpx.Response(200, json={"recipient_id": PSID}),
    httpx.Response(200, json={"message_id": 5}),
    httpx.Response(200, json={"message_id": ""}),
    httpx.Response(200, json=["not", "a", "dict"]),
    httpx.Response(200, text="<html>not json</html>"),
    httpx.Response(200, content=b""),
])
def test_send_text_message_without_a_usable_message_id_returns_empty_list(monkeypatch, response):
    _fake_graph_returning(monkeypatch, response)

    assert facebook.send_text_message("page-token", PSID, "hello") == []


def test_send_text_message_still_raises_graph_errors(monkeypatch):
    def failing(method, path, **kw):
        raise facebook.GraphError(400, "bad token", 190)

    monkeypatch.setattr(facebook, "_graph", failing)

    with pytest.raises(facebook.GraphError):
        facebook.send_text_message("page-token", PSID, "hello")


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
