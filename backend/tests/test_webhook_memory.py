"""S16-8: webhook memory — conversation summary (migration 0026), block-wise compaction after the reply.

Real chain: webhook._process_events -> graph.run_turn -> prompt -> llm, and memory.compact -> llm.complete,
with a fake Claude SDK client (the agent call and the summary call share it; they are told apart by the
system prompt), a fake service DB and patched Facebook I/O. `events` records the order of model calls and
sent messages, so "the summary is requested AFTER the reply was sent" is checked, not assumed.
"""
import copy
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

import app.api.webhook as webhook
import app.services.llm as llm
from app.services import memory, prompt
from tests.conftest import FakeQuery, FakeResult
from tests.test_reply_delivery import PAGE_ID, PSID, SHOP_ID

MESSAGE = "what is the price of Item 1?"  # not a template: it reaches the model
SHOP = {
    "id": SHOP_ID, "name": "Tbilisi Style", "description": "Clothes", "currency": "GEL",
    "bot_language": "auto", "knowledge": "", "bot_enabled": True, "facebook_page_token": "enc",
    "subscription_tier": "free",
}
PRODUCTS = [
    {"id": f"{i:04d}", "name": f"Item {i}", "price": 10 + i, "quantity": 2, "sku": f"S{i}", "description": ""}
    for i in range(3)
]


def pairs(n):
    """n stored messages: user, bot, user, bot, ... (what _save_turn persists)."""
    return [{"role": "user" if i % 2 == 0 else "bot", "content": f"m{i}"} for i in range(n)]


def _pair(text, reply):
    return [{"role": "user", "content": text}, {"role": "bot", "content": reply}]


def _strip_cc(obj):
    """The same structure without cache_control keys (the breakpoint moves, the content must not)."""
    if isinstance(obj, dict):
        return {k: _strip_cc(v) for k, v in obj.items() if k != "cache_control"}
    if isinstance(obj, list):
        return [_strip_cc(v) for v in obj]
    return obj


class NoSummaryColumnQuery(FakeQuery):
    """bot_conversations without the `summary` column: a select that asks for it and an upsert that
    carries it both fail with PostgREST's undefined-column error (42703)."""

    def select(self, *columns, **kwargs):
        self.columns = columns[0] if columns else ""
        return super().select(*columns, **kwargs)

    def execute(self):
        if self.table == "bot_conversations":
            asks = (self.op == "select" and "summary" in self.columns) or (
                self.op == "upsert" and "summary" in self.payload)
            if asks:
                self._db.calls.append(self)
                raise APIError({
                    "code": "42703", "message": "column bot_conversations.summary does not exist",
                    "details": None, "hint": None,
                })
        return super().execute()


class StatefulQuery(FakeQuery):
    """bot_conversations as ONE real row (select / upsert / filtered update), so a race between two
    webhook runs can be replayed: what the second run reads is what the first one has written so far.
    An update with `eq` filters changes the row only if every filter matches it (like PostgREST)."""

    row: dict | None = None  # class-level on purpose: FakeSupabase.table() builds a new query per call

    @classmethod
    def install(cls, db, row):
        """A fresh subclass (own `row`) wired into `db.table`; returns it so tests can read `.row`."""
        store = type("Store", (cls,), {"row": row})
        db.table = lambda name: store(db, name)
        return store

    def execute(self):
        if self.table != "bot_conversations":
            return super().execute()
        self._db.calls.append(self)
        cls = type(self)
        if self.op == "select":
            return FakeResult([copy.deepcopy(cls.row)] if cls.row else [])
        if self.op == "upsert":
            cls.row = {**(cls.row or {}), **copy.deepcopy(self.payload)}
            return FakeResult([copy.deepcopy(cls.row)])
        if self.op == "update":
            row = cls.row
            if row is None or not all(row.get(col) == val for kind, col, val in self.filters if kind == "eq"):
                return FakeResult([])
            row.update(copy.deepcopy(self.payload))
            return FakeResult([copy.deepcopy(row)])
        return super().execute()


class Memory:
    """Fake provider client + fake DB + patched Facebook I/O around the real webhook -> graph -> llm chain."""

    def __init__(self, monkeypatch, db, **settings_update):
        self.db = db
        self.events: list[tuple] = []
        self.requests: list[dict] = []
        self.script: list = []
        self.on_summary = None  # called (once) while the summary model call is being served
        s = webhook.get_settings().model_copy(update=settings_update)
        for module in (webhook, llm):
            monkeypatch.setattr(module, "get_settings", lambda: s)
        self.settings = s

        db.responses[("shops", "select")] = [SHOP]
        db.responses[("products", "select")] = PRODUCTS
        db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 1, "day_count": 1}]
        monkeypatch.setattr(webhook, "get_service_client", lambda: db)
        monkeypatch.setattr(llm, "get_service_client", lambda: db)
        monkeypatch.setattr(webhook, "decrypt", lambda token: "page-token")
        monkeypatch.setattr(
            webhook, "send_text_message", lambda tok, psid, text: self.events.append(("send", text)))
        monkeypatch.setattr(webhook, "download_image", lambda url, timeout=8: None)

        def create(**kwargs):
            self.requests.append(kwargs)
            kind = "summary" if kwargs["system"][0]["text"] == memory.SUMMARY_SYSTEM else "agent"
            self.events.append(("llm", kind))
            if not self.script:
                raise AssertionError("unexpected LLM call")
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            item = {"text": item, "calls": []} if isinstance(item, str) else item
            if kind == "summary" and self.on_summary is not None:
                hook, self.on_summary = self.on_summary, None
                hook()  # the next customer message arrives while this call is in flight
            content =[SimpleNamespace(type="text", text=item["text"])] if item["text"] else []
            content += [SimpleNamespace(type="tool_use", id=i, name=n, input=a) for i, n, a in item["calls"]]
            return SimpleNamespace(
                content=content, stop_reason="tool_use" if item["calls"] else "end_turn",
                usage=SimpleNamespace(input_tokens=100, output_tokens=10, cache_read_input_tokens=0,
                                      cache_creation_input_tokens=0),
            )

        monkeypatch.setattr(llm, "_anthropic_client", lambda s: SimpleNamespace(messages=SimpleNamespace(create=create)))

    @staticmethod
    def calls(*calls, text=""):
        return {"text": text, "calls": list(calls)}

    def seed(self, messages, summary="__absent__", updated_at=None):
        row = {"messages": messages, "updated_at": updated_at or datetime.now(timezone.utc).isoformat()}
        if summary != "__absent__":
            row["summary"] = summary
        self.db.responses[("bot_conversations", "select")] = [row]

    def run(self, text=MESSAGE):
        webhook._process_events({"object": "page", "entry": [{
            "id": PAGE_ID, "messaging": [{"sender": {"id": PSID}, "message": {"text": text}}],
        }]})

    def upserts(self):
        return [c.payload for c in self.db.calls_for("bot_conversations", "upsert")]

    def saved(self):
        (payload,) = self.upserts()
        return payload

    def updates(self):
        return self.db.calls_for("bot_conversations", "update")

    def final(self):
        """The row after the single upsert and the (optional) compaction update, as the DB would hold it."""
        row = dict(self.saved())
        for update in self.updates():
            row.update(update.payload)
        return row

    def kinds(self):
        return [e[1] for e in self.events if e[0] == "llm"]

    def sent(self):
        return [e[1] for e in self.events if e[0] == "send"]

    def usage_rows(self):
        return self.db.calls_for("llm_usage", "insert")

    def first_history_text(self, request):
        return request["messages"][0]["content"][0]["text"]


@pytest.fixture
def m(monkeypatch, service_db):
    return Memory(monkeypatch, service_db)


# --- (a) over the cut: the older part is folded into a summary AFTER the reply was sent ------------
def test_summary_is_requested_after_the_reply_and_replaces_the_older_messages(m):
    m.seed(pairs(16), "S0")
    m.script = ["Answer", "S1"]

    m.run()

    assert m.events == [("llm", "agent"), ("send", "Answer"), ("llm", "summary")]
    agent_request, summary_request = m.requests
    assert "Previous summary:\nS0" in summary_request["messages"][0]["content"][0]["text"]
    assert "tools" not in summary_request
    full = pairs(16) + _pair(MESSAGE, "Answer")
    assert len(full) == 18
    # the turn is stored first, uncompacted and with the OLD summary (the model call comes after it) ...
    stored = m.saved()
    assert stored["messages"] == full and stored["summary"] == "S0"
    # ... then folded by a conditional update that only matches the row just written
    (update,) = m.updates()
    assert update.payload == {"messages": full[-8:], "summary": "S1"}
    assert ("eq", "updated_at", stored["updated_at"]) in update.filters
    assert ("eq", "shop_id", SHOP_ID) in update.filters and ("eq", "psid", PSID) in update.filters
    saved = m.final()
    assert saved["messages"] == full[-8:]
    assert saved["messages"][0]["role"] == "user"
    assert saved["summary"] == "S1"
    assert len(m.usage_rows()) == 2  # the agent call and the summary call
    # the agent call itself saw the whole stored history and the OLD summary
    assert m.first_history_text(agent_request).startswith(prompt.SUMMARY_HEADER)
    assert len(agent_request["messages"]) == 16 + 1


# --- (b) the summary call fails: nothing is lost -----------------------------------------------------
def test_failed_summary_keeps_all_messages_and_the_old_summary(m, caplog):
    m.seed(pairs(16), "S0")
    m.script = ["Answer", ValueError("summary model down")]

    with caplog.at_level(logging.WARNING, logger="app"):
        m.run()

    assert m.sent() == ["Answer"]  # the customer already has the reply
    saved = m.saved()
    assert saved["messages"] == pairs(16) + _pair(MESSAGE, "Answer")  # all 18
    assert saved["summary"] == "S0"
    assert m.updates() == []  # nothing to apply
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(SHOP_ID in w and "summary failed" in w for w in warnings)
    assert not any(PSID in w for w in warnings)
    assert len(m.usage_rows()) == 1  # only the agent call produced usage


def test_empty_summary_keeps_all_messages(m):
    m.seed(pairs(16), "S0")
    m.script = ["Answer", "   "]

    m.run()

    saved = m.saved()
    assert len(saved["messages"]) == 18 and saved["summary"] == "S0"


# --- (c) below the cut: no summary call --------------------------------------------------------------
def test_no_summary_call_until_the_history_exceeds_the_cut(m):
    m.seed(pairs(14), "S0")
    m.script = ["Answer"]

    m.run()

    assert m.kinds() == ["agent"]
    saved = m.saved()
    assert len(saved["messages"]) == 16 and saved["summary"] == "S0"


# --- (d) a template turn never calls the model --------------------------------------------------------
def test_template_turn_on_a_long_history_makes_no_summary_call(m):
    m.seed(pairs(16), "S0")

    m.run("გამარჯობა")

    assert m.requests == []
    saved = m.saved()
    assert len(saved["messages"]) == 18 and saved["summary"] == "S0"
    assert m.usage_rows() == []


# --- (e) the memory load fails (A-042: the error propagates, no old-behaviour fallback) ---------------
def test_missing_summary_column_is_an_error(m, service_db):
    service_db.table = lambda name: NoSummaryColumnQuery(service_db, name)
    m.seed(pairs(18))
    m.script = ["A1"]

    with pytest.raises(APIError):
        m.run()

    # S20-3: the pause lookup (`bot_paused_until`) is a separate select — this test is about the memory load
    selects = [
        c.columns for c in service_db.calls_for("bot_conversations", "select")
        if c.columns != "bot_paused_until"
    ]
    assert selects == ["messages,updated_at,summary"]  # one select; no retry without `summary`
    assert m.kinds() == [] and m.sent() == []  # no LLM call, no reply
    assert m.upserts() == []


def test_memory_select_error_propagates(m, service_db):
    service_db.errors[("bot_conversations", "select")] = RuntimeError("db down")
    m.script = ["Answer"]

    with pytest.raises(RuntimeError):
        m.run()

    assert m.requests == [] and m.sent() == []  # no empty-history answer for a conversation we could not read


# --- (f) an old conversation starts over ---------------------------------------------------------------
def test_conversation_older_than_the_memory_window_drops_its_summary(m):
    m.seed(pairs(4), "OLD", updated_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    m.script = ["Answer"]

    m.run()

    request = m.requests[0]
    assert len(request["messages"]) == 1
    assert "OLD" not in json.dumps(request) and prompt.SUMMARY_HEADER not in json.dumps(request)
    saved = m.saved()
    assert saved["messages"] == _pair(MESSAGE, "Answer")
    assert "summary" in saved and saved["summary"] is None  # the column is cleared


# --- (g) the summary sits in front of the history; the cached prefix survives the next turn ----------
def test_summary_header_opens_the_first_history_turn(m):
    m.seed(pairs(10), "S0 wants a red shirt")
    m.script = ["Answer"]

    m.run()

    first = m.first_history_text(m.requests[0])
    assert first.startswith(prompt.SUMMARY_HEADER)
    assert "S0 wants a red shirt" in first and first.endswith("m0")


def test_history_prefix_of_the_next_turn_is_byte_identical(m):
    m.seed(pairs(10), "S0")
    m.script = ["A1", "A2"]

    m.run()
    saved = m.saved()
    assert len(saved["messages"]) == 12 and saved["summary"] == "S0"  # no cut yet: the prefix only grows
    m.seed(saved["messages"], saved["summary"])
    m.db.calls.clear()
    m.run("and Item 2?")

    req_n, req_n1 = m.requests
    n_hist = 10
    assert _strip_cc(req_n1["messages"][:n_hist]) == _strip_cc(req_n["messages"][:n_hist])
    assert req_n1["system"] == req_n["system"]
    # the breakpoint moved to the end of the (longer) history, never onto the variable final turn
    assert req_n["messages"][n_hist - 1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert req_n1["messages"][n_hist + 1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in b for b in req_n1["messages"][-1]["content"])


# --- (h) over the customer limit: the summary is untouched, no model call --------------------------------
def test_over_limit_turn_keeps_a_fresh_summary(m):
    m.db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 31, "day_count": 1}]
    m.db.responses[("bot_customers", "select")] = [{"created_at": "2026-10-01T10:00:00+00:00"}]
    m.db.counts[("bot_customers", "select")] = 30  # rank 31 -> over the free limit
    m.seed(pairs(16), "S0")

    m.run()

    assert m.requests == []
    assert m.sent() == [webhook.OPERATOR_SOON_REPLY]
    saved = m.saved()
    assert saved["summary"] == "S0"  # the loaded summary is written back unchanged (no model call)
    assert saved["needs_attention"] is True
    assert len(saved["messages"]) == 18
    assert m.updates() == []


def test_disabled_bot_keeps_a_fresh_summary(m, monkeypatch):
    s = webhook.get_settings().model_copy(update={"anthropic_api_key": ""})
    monkeypatch.setattr(webhook, "get_settings", lambda: s)
    m.seed(pairs(16), "S0")

    m.run()

    assert m.requests == []
    assert m.saved()["summary"] == "S0"


# --- (h2) over the limit / disabled on an OLD conversation: its summary is cleared (S16-11) ------------------
def test_over_limit_turn_on_an_old_conversation_clears_the_summary(m):
    m.db.rpc_responses["track_bot_customer"] = [{"monthly_unique": 31, "day_count": 1}]
    m.db.responses[("bot_customers", "select")] = [{"created_at": "2026-10-01T10:00:00+00:00"}]
    m.db.counts[("bot_customers", "select")] = 30
    m.seed(pairs(16), "OLD", updated_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())

    m.run()

    assert m.requests == [] and m.updates() == []  # no model call
    saved = m.saved()
    assert "summary" in saved and saved["summary"] is None  # not revived by the next agent turn
    assert saved["messages"] == _pair(MESSAGE, webhook.OPERATOR_SOON_REPLY)
    assert saved["needs_attention"] is True


def test_disabled_bot_on_an_old_conversation_clears_the_summary(m, monkeypatch):
    s = webhook.get_settings().model_copy(update={"anthropic_api_key": ""})
    monkeypatch.setattr(webhook, "get_settings", lambda: s)
    m.seed(pairs(16), "OLD", updated_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())

    m.run()

    assert m.requests == []
    saved = m.saved()
    assert "summary" in saved and saved["summary"] is None
    assert len(saved["messages"]) == 2


# --- (i) memory switched off -----------------------------------------------------------------------------
def test_memory_off_means_no_history_no_summary_and_no_save(monkeypatch, service_db):
    m = Memory(monkeypatch, service_db, bot_memory_messages=0)
    m.seed(pairs(16), "S0")
    m.script = ["Answer"]

    m.run()

    assert m.kinds() == ["agent"]
    assert len(m.requests[0]["messages"]) == 1  # no history, no summary
    assert prompt.SUMMARY_HEADER not in json.dumps(m.requests[0])
    assert m.upserts() == []


def test_memory_off_handoff_saves_only_the_last_pair_without_summary(monkeypatch, service_db):
    m = Memory(monkeypatch, service_db, bot_memory_messages=0)
    m.seed(pairs(16), "S0")
    m.script = [Memory.calls(("h1", "request_human", {"reason": "complaint"}))]

    m.run()

    assert m.kinds() == ["agent"]
    saved = m.saved()
    assert saved["needs_attention"] is True and len(saved["messages"]) == 2
    assert "summary" not in saved


# --- (j) request_human on a long history: flagged AND cut ---------------------------------------------------
def test_request_human_turn_is_flagged_and_still_compacted(m):
    m.seed(pairs(16), "S0")
    m.script = [Memory.calls(("h1", "request_human", {"reason": "complaint"})), "S1"]

    m.run()

    assert m.kinds() == ["agent", "summary"]
    saved = m.final()
    assert m.saved()["needs_attention"] is True  # flagged in the first write
    assert "needs_attention" not in m.updates()[0].payload
    assert len(saved["messages"]) == 8 and saved["messages"][0]["role"] == "user"
    assert saved["summary"] == "S1"


# --- (k) the model call does not sit between the send and the save (S16-11) ---------------------------------
def _stateful(m, messages, summary):
    row = {"shop_id": SHOP_ID, "psid": PSID, "messages": messages, "summary": summary,
           "updated_at": datetime.now(timezone.utc).isoformat()}
    return StatefulQuery.install(m.db, row)


def test_message_arriving_during_the_summary_call_sees_the_previous_turn_and_nothing_is_lost(m):
    """A's summary call is in flight when B arrives. Invariant asserted: B's request history contains A's
    pair, and the stored row holds A's pair followed by B's pair (no turn lost, none duplicated); A's
    late conditional update matches nothing (the row's updated_at is B's), so it cannot clobber B's
    newer row - the summary and cut in the row are B's own."""
    store = _stateful(m, pairs(16), "S0")
    m.script = ["AnswerA", "S1", "AnswerB", "S2"]
    m.on_summary = lambda: m.run("and Item 2?")

    m.run()

    assert m.kinds() == ["agent", "summary", "agent", "summary"]  # A agent, A summary (B ran inside), B ...
    b_agent = m.requests[2]
    assert len(b_agent["messages"]) == 18 + 1  # A's pair is in B's history
    text = json.dumps(b_agent, ensure_ascii=False)
    assert MESSAGE in text and "AnswerA" in text
    assert m.sent() == ["AnswerA", "AnswerB"]
    full = pairs(16) + _pair(MESSAGE, "AnswerA") + _pair("and Item 2?", "AnswerB")
    assert store.row["messages"] == full[-8:]  # B's compaction; A's pair and B's pair both kept, in order
    assert store.row["messages"][-4:] == _pair(MESSAGE, "AnswerA") + _pair("and Item 2?", "AnswerB")
    assert store.row["summary"] == "S2"  # A's S1 was dropped by its own failed condition, not applied
    a_update, b_update = m.updates()[1], m.updates()[0]  # B's update executes first (nested), A's after
    assert b_update.payload["summary"] == "S2" and a_update.payload["summary"] == "S1"
    assert dict((c, v) for k, c, v in a_update.filters if c == "updated_at")["updated_at"] != store.row["updated_at"]


def test_template_reply_during_the_summary_call_is_not_overwritten_by_the_late_compaction(m):
    """Same race, B is a template turn (no model call): the stored row ends with A's pair AND B's pair
    (20 messages, uncompacted, the loaded summary) - A's late update does not replace it."""
    store = _stateful(m, pairs(16), "S0")
    m.script = ["AnswerA", "S1"]
    m.on_summary = lambda: m.run("გამარჯობა")

    m.run()

    b_reply = m.sent()[1]
    assert store.row["messages"] == pairs(16) + _pair(MESSAGE, "AnswerA") + _pair("გამარჯობა", b_reply)
    assert store.row["summary"] == "S0"
    assert m.kinds() == ["agent", "summary"]  # B made no model call


def test_late_compaction_is_applied_when_nothing_newer_was_saved(m):
    store = _stateful(m, pairs(16), "S0")
    m.script = ["Answer", "S1"]

    m.run()

    full = pairs(16) + _pair(MESSAGE, "Answer")
    assert store.row["messages"] == full[-8:] and store.row["summary"] == "S1"


def test_failed_compaction_update_loses_nothing(m, caplog):
    m.seed(pairs(16), "S0")
    m.db.errors[("bot_conversations", "update")] = RuntimeError("db down")
    m.script = ["Answer", "S1"]

    with caplog.at_level(logging.WARNING, logger="app"):
        m.run()  # must not raise

    saved = m.saved()
    assert saved["messages"] == pairs(16) + _pair(MESSAGE, "Answer") and saved["summary"] == "S0"
    assert any("compaction save failed" in r.getMessage() and SHOP_ID in r.getMessage() for r in caplog.records)
    assert not any(PSID in r.getMessage() for r in caplog.records)


def test_handoff_save_error_skips_compaction(m, service_db, caplog):
    """A-042: the flagged upsert fails -> ONE attempt (no plain retry), no summary call, no update; the
    reply was already sent and is not repeated (the caller logs a WARNING)."""
    class NoAttentionQuery(FakeQuery):
        def execute(self):
            if self.table == "bot_conversations" and self.op == "upsert" and "needs_attention" in self.payload:
                self._db.calls.append(self)
                raise RuntimeError("column needs_attention does not exist")
            return super().execute()

    service_db.table = lambda name: NoAttentionQuery(service_db, name)
    m.seed(pairs(16), "S0")
    m.script = [Memory.calls(("h1", "request_human", {"reason": "complaint"})), "S1"]

    with caplog.at_level(logging.WARNING, logger="app"):
        m.run()  # must not raise

    attempts = service_db.calls_for("bot_conversations", "upsert")
    assert len(attempts) == 1 and attempts[0].payload["needs_attention"] is True
    assert m.kinds() == ["agent"]  # no summary call for a turn that was not stored
    assert m.updates() == []
    assert len(m.sent()) == 1
    assert any("საუბრის შენახვა ვერ მოხერხდა" in r.getMessage() for r in caplog.records)


def test_no_compaction_when_the_first_write_failed(m):
    m.seed(pairs(16), "S0")
    m.db.errors[("bot_conversations", "upsert")] = RuntimeError("db down")
    m.script = ["Answer"]

    m.run()

    assert m.kinds() == ["agent"]  # no summary call for a turn that was not stored
    assert m.updates() == []
