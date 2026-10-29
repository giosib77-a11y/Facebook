"""S17-4: upload_knowledge / clear_knowledge - the upload is saved with one write and returns at once;
the FAQ is generated in a background task and saved only if the shop's document is still the same;
missing-0027 tolerance, rate limit, PDF text cap. Fake Claude client + fake Supabase only - no network,
no .env. (TestClient runs background tasks after the response, before `post()` returns.)"""
import asyncio
import io
import logging
import uuid
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, UploadFile
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import app.api.shops
import app.services.pdf_extract as pdf_extract
from app.core.security import CurrentAuth, get_current_auth
from app.main import app as fastapi_app
from app.services import knowledge, llm
from conftest import USER_ID, FakeQuery

SHOP_ID = str(uuid.uuid4())
URL = f"/shops/{SHOP_ID}/knowledge"
TS = {"created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}
PDF = {"file": ("k.pdf", b"%PDF-1.4", "application/pdf")}
DOC = "Delivery in Tbilisi takes 1-2 days and costs 5 GEL."
FAQ1 = "Q: How much is delivery?\nA: 5 GEL."
FAQ2 = "Q: How long does delivery take?\nA: 1-2 days."
MISSING = "Could not find the 'knowledge_faq' column of 'shops' in the schema cache"


def _response(text):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )


def shop_row(**extra):
    return {"id": SHOP_ID, "owner_id": USER_ID, "name": "S", "currency": "GEL",
            "bot_enabled": True, **TS, **extra}


class Fake:
    """Fake Claude client (script items: a FAQ text or an Exception) wired to the fake service DB."""

    def __init__(self, monkeypatch, service_db):
        self.requests = []
        self.script = []
        self.on_call = None  # hook run inside the LLM call (simulates something happening meanwhile)
        self.updates_at_call = []  # how many shops updates had already run when the LLM was called

        def create(**kwargs):
            self.requests.append(kwargs)
            self.updates_at_call.append(len(service_db.calls_for("shops", "update")))
            if self.on_call:
                self.on_call()
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return _response(item)

        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        monkeypatch.setattr(llm, "_anthropic_client", lambda s: client)
        monkeypatch.setattr(llm, "get_service_client", lambda: service_db)


@pytest.fixture
def fake(monkeypatch, service_db):
    return Fake(monkeypatch, service_db)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(app.api.shops, "extract_pdf_text", lambda content: DOC)
    monkeypatch.setattr(app.api.shops, "_faq_column_warned", [False])


@pytest.fixture
def paid(user_db, service_db):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "standard"}]
    service_db.responses[("shops", "update")] = [shop_row(knowledge_filename="k.pdf")]
    # what the background task reads back to check the document is still the same
    service_db.responses[("shops", "select")] = [{"knowledge": DOC}]


def _faq_warnings(caplog):
    return [r for r in caplog.records
            if r.levelno == logging.WARNING and "shops.knowledge_faq missing" in r.getMessage()]


def _warnings(caplog, needle):
    return [r for r in caplog.records if r.levelno == logging.WARNING and needle in r.getMessage()]


FIRST_WRITE = {"knowledge": DOC, "knowledge_filename": "k.pdf", "knowledge_faq": None}


# (1) happy path: one write now, the FAQ in the background

def test_paid_upload_writes_once_then_saves_faq_in_background(client, user_db, service_db, fake, paid):
    fake.script = [FAQ1]
    r = client.post(URL, files=PDF)
    assert r.status_code == 200
    body = r.json()
    assert "knowledge" not in body and "knowledge_faq" not in body
    updates = service_db.calls_for("shops", "update")
    assert len(updates) == 2
    assert updates[0].payload == FIRST_WRITE  # the upload itself: FAQ null, no LLM waited for
    assert ("eq", "id", SHOP_ID) in updates[0].filters
    assert updates[1].payload == {"knowledge_faq": FAQ1}
    assert ("eq", "id", SHOP_ID) in updates[1].filters  # pinned to this shop
    assert user_db.calls_for("shops", "update") == []
    usage = service_db.calls_for("llm_usage", "insert")
    assert len(usage) == 1 and usage[0].payload["shop_id"] == SHOP_ID
    assert len(fake.requests) == 1
    assert fake.updates_at_call == [1]  # the LLM ran only after the upload had been written


def test_handler_returns_before_any_llm_call(user_db, service_db, fake, paid):
    """Called directly (no TestClient): when the handler returns, the LLM has not run; the FAQ is a queued task."""
    fake.script = [FAQ1]
    tasks = BackgroundTasks()
    auth = CurrentAuth(user_id=USER_ID, email="s@t.local", client=user_db)
    out = app.api.shops.upload_knowledge(
        uuid.UUID(SHOP_ID), tasks, UploadFile(file=io.BytesIO(b"%PDF-1.4"), filename="k.pdf"), auth)
    assert out["id"] == SHOP_ID
    assert fake.requests == []
    assert [u.payload for u in service_db.calls_for("shops", "update")] == [FIRST_WRITE]
    assert len(tasks.tasks) == 1
    asyncio.run(tasks())  # now the response is "sent": run the background work
    assert len(fake.requests) == 1
    assert [u.payload for u in service_db.calls_for("shops", "update")][1:] == [{"knowledge_faq": FAQ1}]


# (2) rejected before any LLM call / write

def _assert_untouched(fake, service_db):
    assert fake.requests == []
    assert service_db.calls_for("shops", "update") == []
    assert service_db.calls_for("llm_usage", "insert") == []


def test_free_tier_403_no_llm_no_write(client, user_db, service_db, fake):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "free"}]
    assert client.post(URL, files=PDF).status_code == 403
    _assert_untouched(fake, service_db)


def test_foreign_shop_404_no_llm_no_write(client, user_db, service_db, fake):
    user_db.responses[("shops", "select")] = []
    assert client.post(URL, files=PDF).status_code == 404
    _assert_untouched(fake, service_db)


def test_non_pdf_400(client, paid, service_db, fake):
    r = client.post(URL, files={"file": ("k.txt", b"hello", "text/plain")})
    assert r.status_code == 400
    _assert_untouched(fake, service_db)


def test_empty_file_400(client, paid, service_db, fake):
    assert client.post(URL, files={"file": ("k.pdf", b"", "application/pdf")}).status_code == 400
    _assert_untouched(fake, service_db)


def test_oversize_file_400(client, paid, service_db, fake):
    big = b"%PDF" + b"0" * app.api.shops.MAX_PDF_BYTES
    assert client.post(URL, files={"file": ("k.pdf", big, "application/pdf")}).status_code == 400
    _assert_untouched(fake, service_db)


def test_extraction_error_400(client, paid, service_db, fake, monkeypatch):
    def boom(content):
        raise ValueError("PDF ფაილის წაკითხვა ვერ მოხერხდა")

    monkeypatch.setattr(app.api.shops, "extract_pdf_text", boom)
    assert client.post(URL, files=PDF).status_code == 400
    _assert_untouched(fake, service_db)


# (3) LLM failure -> the upload is still saved, FAQ null

def test_llm_failure_still_saves_with_null_faq(client, service_db, fake, paid, caplog):
    fake.script = [RuntimeError("boom")] * 4  # more than the retries need
    with caplog.at_level(logging.WARNING):
        r = client.post(URL, files=PDF)
    assert r.status_code == 200
    updates = service_db.calls_for("shops", "update")
    assert len(updates) == 1  # the FAQ stays null: nothing more is written
    assert updates[0].payload == FIRST_WRITE
    failed = _warnings(caplog, "knowledge FAQ failed")
    assert len(failed) == 1 and "RuntimeError" in failed[0].getMessage()
    assert DOC not in "\n".join(r.getMessage() for r in caplog.records)


# (4) re-upload replaces the FAQ; a failed re-generation does not keep the old one

def test_reupload_replaces_faq_and_failure_clears_it(client, service_db, fake, paid):
    fake.script = [FAQ1, FAQ2]
    assert client.post(URL, files=PDF).status_code == 200
    assert client.post(URL, files=PDF).status_code == 200
    fake.script = [RuntimeError("boom")] * 4
    assert client.post(URL, files=PDF).status_code == 200
    payloads = [c.payload for c in service_db.calls_for("shops", "update")]
    # every upload first nulls the FAQ; the failed third one never gets a new FAQ, so the old one is gone
    assert [p.get("knowledge_faq", "-") for p in payloads] == [None, FAQ1, None, FAQ2, None]
    assert "knowledge" in payloads[0] and "knowledge" in payloads[2] and "knowledge" in payloads[4]


# (4b) stale background result: the document changed while the LLM was working

def test_reupload_during_generation_drops_the_stale_faq(client, service_db, fake, paid):
    def another_upload_lands():
        service_db.responses[("shops", "select")] = [{"knowledge": "A NEWER DOCUMENT"}]

    fake.on_call = another_upload_lands
    fake.script = [FAQ1]
    assert client.post(URL, files=PDF).status_code == 200
    assert len(fake.requests) == 1
    assert [u.payload for u in service_db.calls_for("shops", "update")] == [FIRST_WRITE]  # no FAQ write


def test_clear_during_generation_drops_the_stale_faq(client, service_db, fake, paid):
    fake.on_call = lambda: service_db.responses.__setitem__(("shops", "select"), [{"knowledge": None}])
    fake.script = [FAQ1]
    assert client.post(URL, files=PDF).status_code == 200
    assert [u.payload for u in service_db.calls_for("shops", "update")] == [FIRST_WRITE]


def test_shop_gone_during_generation_drops_the_faq(client, service_db, fake, paid):
    fake.on_call = lambda: service_db.responses.__setitem__(("shops", "select"), [])
    fake.script = [FAQ1]
    assert client.post(URL, files=PDF).status_code == 200
    assert [u.payload for u in service_db.calls_for("shops", "update")] == [FIRST_WRITE]


def test_editing_name_during_generation_does_not_block_the_faq(client, service_db, fake, paid):
    # a settings edit bumps shops.updated_at (trigger) but leaves the document alone
    fake.on_call = lambda: service_db.responses.__setitem__(
        ("shops", "select"), [{"knowledge": DOC, "name": "Renamed", "updated_at": "2026-12-12T00:00:00Z"}])
    fake.script = [FAQ1]
    assert client.post(URL, files=PDF).status_code == 200
    assert [u.payload for u in service_db.calls_for("shops", "update")][1:] == [{"knowledge_faq": FAQ1}]


def test_faq_save_error_in_background_is_contained(client, service_db, fake, paid, caplog):
    fake.on_call = lambda: service_db.errors.__setitem__(("shops", "update"), RuntimeError("secret " + DOC))
    fake.script = [FAQ1]
    with caplog.at_level(logging.WARNING):
        r = client.post(URL, files=PDF)
    assert r.status_code == 200  # the upload itself was already saved and answered
    saved = _warnings(caplog, "knowledge FAQ save failed")
    assert len(saved) == 1 and "RuntimeError" in saved[0].getMessage()
    assert "secret" not in "\n".join(r.getMessage() for r in caplog.records)


def test_faq_read_error_in_background_is_contained(client, service_db, fake, paid, caplog):
    fake.on_call = lambda: service_db.errors.__setitem__(("shops", "select"), RuntimeError("db down"))
    fake.script = [FAQ1]
    with caplog.at_level(logging.WARNING):
        assert client.post(URL, files=PDF).status_code == 200
    assert len(_warnings(caplog, "knowledge FAQ save failed")) == 1
    assert [u.payload for u in service_db.calls_for("shops", "update")] == [FIRST_WRITE]


# (5) migration 0027 not applied

class NoFaqColumnQuery(FakeQuery):
    """update with a knowledge_faq key fails like PostgREST does on a missing column."""

    def __init__(self, db, table, error):
        super().__init__(db, table)
        self._error = error
        db.attempts = getattr(db, "attempts", [])

    def execute(self):
        if self.op == "update" and "knowledge_faq" in (self.payload or {}):
            self._db.attempts.append(dict(self.payload))
            raise self._error
        return super().execute()


def _missing_column(service_db, error=None):
    err = error or Exception(MISSING)
    service_db.table = lambda name: NoFaqColumnQuery(service_db, name, err)


def test_missing_column_retries_without_faq_and_warns_once(client, service_db, fake, paid, caplog):
    _missing_column(service_db)
    fake.script = [FAQ1, FAQ2]
    with caplog.at_level(logging.WARNING):
        assert client.post(URL, files=PDF).status_code == 200
        assert client.post(URL, files=PDF).status_code == 200
    saved = [c.payload for c in service_db.calls_for("shops", "update")]
    assert saved == [{"knowledge": DOC, "knowledge_filename": "k.pdf"}] * 2
    assert len(service_db.attempts) == 2  # each upload tried the full payload first
    assert len(_faq_warnings(caplog)) == 1
    assert fake.requests == []  # column missing -> no background FAQ, so no LLM call (no wasted cost)


def test_missing_column_postgrest_error_also_tolerated(client, service_db, fake, paid):
    err = APIError({"message": MISSING, "code": "PGRST204", "hint": None, "details": None})
    _missing_column(service_db, err)
    fake.script = [FAQ1]
    assert client.post(URL, files=PDF).status_code == 200
    assert len(service_db.calls_for("shops", "update")) == 1
    assert fake.requests == []


def test_other_write_error_propagates(user_db, service_db, fake, paid):
    service_db.errors[("shops", "update")] = Exception("connection reset")
    fake.script = [FAQ1]
    fastapi_app.dependency_overrides[get_current_auth] = lambda: CurrentAuth(
        user_id=USER_ID, email="s@t.local", client=user_db)
    try:
        r = TestClient(fastapi_app, raise_server_exceptions=False).post(URL, files=PDF)
    finally:
        fastapi_app.dependency_overrides.clear()
    assert r.status_code == 500
    assert len(service_db.calls_for("shops", "update")) == 1  # one attempt, no second FAQ-less one


def test_other_postgrest_error_is_400_without_retry(client, service_db, fake, paid):
    service_db.errors[("shops", "update")] = APIError(
        {"message": "permission denied", "code": "XX000", "hint": None, "details": None})
    fake.script = [FAQ1]
    assert client.post(URL, files=PDF).status_code == 400


def test_clear_tolerates_missing_column(client, user_db, service_db, caplog):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    service_db.responses[("shops", "update")] = [shop_row()]
    _missing_column(service_db)
    with caplog.at_level(logging.WARNING):
        assert client.delete(URL).status_code == 200
    saved = [c.payload for c in service_db.calls_for("shops", "update")]
    assert saved == [{"knowledge": None, "knowledge_filename": None}]
    assert len(_faq_warnings(caplog)) == 1


# (6) clear: all three columns null, no LLM

def test_clear_nulls_all_three_without_llm(client, user_db, service_db, fake):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID}]
    service_db.responses[("shops", "update")] = [shop_row()]
    assert client.delete(URL).status_code == 200
    updates = service_db.calls_for("shops", "update")
    assert len(updates) == 1
    assert updates[0].payload == {"knowledge": None, "knowledge_filename": None, "knowledge_faq": None}
    assert ("eq", "id", SHOP_ID) in updates[0].filters
    assert fake.requests == []


# (7) rate limit

def test_eleventh_upload_in_an_hour_is_429(client, service_db, fake, paid):
    fake.script = [FAQ1] * 20
    codes = [client.post(URL, files=PDF).status_code for _ in range(11)]
    assert codes == [200] * 10 + [429]
    assert len(fake.requests) == 10
    assert len(service_db.calls_for("shops", "update")) == 20  # 10 uploads + 10 background FAQ writes


# (7b) until the background FAQ lands the bot keeps the old behaviour: the 20000-char knowledge clip

def test_bot_prompt_without_faq_uses_the_old_knowledge_clip():
    from app.services import prompt

    shop = {"name": "S", "currency": "GEL", "knowledge": "x" * 30_000, "knowledge_faq": None}
    layer2 = prompt.build_layer2(shop, [])
    head, _, clip = layer2.partition("SHOP KNOWLEDGE (from the shop's document)\n")
    assert clip.startswith("x" * 19_000) and len(clip) <= prompt.KNOWLEDGE_CLIP_CHARS + 2  # clipped, not 30000
    assert "short FAQ" not in layer2


# (8) PDF text cap

def _fake_reader(monkeypatch, texts):
    pages = [SimpleNamespace(extract_text=lambda t=t: t) for t in texts]
    monkeypatch.setattr(pdf_extract, "PdfReader", lambda stream: SimpleNamespace(pages=pages))


def test_pdf_cap_is_50000(monkeypatch):
    assert pdf_extract.MAX_CHARS == 50_000
    assert knowledge.FAQ_INPUT_MAX_CHARS == pdf_extract.MAX_CHARS  # the whole extracted text reaches build_faq
    _fake_reader(monkeypatch, ["a" * 30_000])
    assert pdf_extract.extract_pdf_text(b"%PDF") == "a" * 30_000  # not cut any more

    _fake_reader(monkeypatch, ["a" * 60_000])
    text = pdf_extract.extract_pdf_text(b"%PDF")
    assert text == "a" * 50_000 + "\n…(შემოკლებულია)"
