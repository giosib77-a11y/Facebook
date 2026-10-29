"""S17-4: upload_knowledge / clear_knowledge - FAQ on upload, one write, missing-0027 tolerance,
rate limit, PDF text cap. Fake Claude client + fake Supabase only - no network, no .env."""
import logging
import uuid
from types import SimpleNamespace

import pytest
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

        def create(**kwargs):
            self.requests.append(kwargs)
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


def _faq_warnings(caplog):
    return [r for r in caplog.records
            if r.levelno == logging.WARNING and "shops.knowledge_faq missing" in r.getMessage()]


# (1) happy path: FAQ + one write

def test_paid_upload_builds_faq_and_writes_once(client, user_db, service_db, fake, paid):
    fake.script = [FAQ1]
    r = client.post(URL, files=PDF)
    assert r.status_code == 200
    body = r.json()
    assert "knowledge" not in body and "knowledge_faq" not in body
    updates = service_db.calls_for("shops", "update")
    assert len(updates) == 1
    assert updates[0].payload == {"knowledge": DOC, "knowledge_filename": "k.pdf", "knowledge_faq": FAQ1}
    assert ("eq", "id", SHOP_ID) in updates[0].filters
    assert user_db.calls_for("shops", "update") == []
    usage = service_db.calls_for("llm_usage", "insert")
    assert len(usage) == 1 and usage[0].payload["shop_id"] == SHOP_ID
    assert len(fake.requests) == 1


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
    assert len(updates) == 1
    assert updates[0].payload == {"knowledge": DOC, "knowledge_filename": "k.pdf", "knowledge_faq": None}
    assert any("knowledge FAQ failed" in r.getMessage() for r in caplog.records)


# (4) re-upload replaces the FAQ; a failed re-generation does not keep the old one

def test_reupload_replaces_faq_and_failure_clears_it(client, service_db, fake, paid):
    fake.script = [FAQ1, FAQ2]
    assert client.post(URL, files=PDF).status_code == 200
    assert client.post(URL, files=PDF).status_code == 200
    fake.script = [RuntimeError("boom")] * 4
    assert client.post(URL, files=PDF).status_code == 200
    payloads = [c.payload for c in service_db.calls_for("shops", "update")]
    assert [p["knowledge_faq"] for p in payloads] == [FAQ1, FAQ2, None]


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


def test_missing_column_postgrest_error_also_tolerated(client, service_db, fake, paid):
    err = APIError({"message": MISSING, "code": "PGRST204", "hint": None, "details": None})
    _missing_column(service_db, err)
    fake.script = [FAQ1]
    assert client.post(URL, files=PDF).status_code == 200
    assert len(service_db.calls_for("shops", "update")) == 1


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
    assert len(service_db.calls_for("shops", "update")) == 10


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
