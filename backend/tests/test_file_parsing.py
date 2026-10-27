"""N-01 / N-02: heavy file parsing must not block the event loop and must be bounded."""
import inspect
import uuid

import pytest

import app.api.products
import app.api.shops
import app.services.pdf_extract as pdf_extract
from conftest import USER_ID

SHOP_ID = str(uuid.uuid4())
SUFFIX = "\n…(შემოკლებულია)"


def minimal_pdf(text: str) -> bytes:
    """A real one-page text PDF (Helvetica, ASCII text) with a correct xref table."""
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


class FakePage:
    def __init__(self, text, log):
        self._text, self._log = text, log

    def extract_text(self):
        self._log.append(self)
        if isinstance(self._text, Exception):
            raise self._text
        return self._text


def fake_reader(monkeypatch, texts):
    """Replaces PdfReader with one whose pages return `texts`; returns the extract_text call log."""
    log = []
    pages = [FakePage(t, log) for t in texts]

    class FakeReader:
        def __init__(self, stream):
            self.pages = pages

    monkeypatch.setattr(pdf_extract, "PdfReader", FakeReader)
    return log, pages


# ── N-02: bounded PDF extraction ──

def test_f1_pdf_page_cap(monkeypatch):
    log, _ = fake_reader(monkeypatch, ["x"] * 400)
    pdf_extract.extract_pdf_text(b"%PDF")
    assert len(log) == pdf_extract.MAX_PAGES


def test_f2_pdf_stops_once_max_chars_exceeded(monkeypatch):
    big = "a" * 15000
    log, pages = fake_reader(monkeypatch, [big] * 10)
    text = pdf_extract.extract_pdf_text(b"%PDF")
    assert log == pages[:2]  # 15000 + 2 + 15000 > MAX_CHARS → pages 3..10 never touched
    assert text.endswith(SUFFIX)
    assert text == ("\n\n".join([big] * 10))[: pdf_extract.MAX_CHARS] + SUFFIX


def test_f3_small_pdf_unchanged(monkeypatch):
    fake_reader(monkeypatch, ["  Hello \n", "", RuntimeError("bad page"), None, "World"])
    assert pdf_extract.extract_pdf_text(b"%PDF") == "Hello\n\nWorld"

    fake_reader(monkeypatch, ["", "   "])
    with pytest.raises(ValueError, match="დასკანერებული"):
        pdf_extract.extract_pdf_text(b"%PDF")


# ── Real pypdf (no fake reader): guards dependency upgrades ──

def test_f5_real_pypdf_extracts_text():
    assert pdf_extract.extract_pdf_text(minimal_pdf("Delivery in Tbilisi 5 GEL")) == (
        "Delivery in Tbilisi 5 GEL"
    )


def test_f6_real_pypdf_rejects_non_pdf():
    with pytest.raises(ValueError, match="წაკითხვა ვერ მოხერხდა"):
        pdf_extract.extract_pdf_text(b"this is not a pdf at all")


def test_f7_knowledge_upload_with_real_pdf(client, user_db, service_db):
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "standard"}]
    service_db.responses[("shops", "update")] = [{
        "id": SHOP_ID, "owner_id": USER_ID, "name": "S", "currency": "GEL", "bot_enabled": True,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        "knowledge_filename": "k.pdf",
    }]
    r = client.post(
        f"/shops/{SHOP_ID}/knowledge",
        files={"file": ("k.pdf", minimal_pdf("Open daily 10-20"), "application/pdf")},
    )
    assert r.status_code == 200
    updates = service_db.calls_for("shops", "update")
    assert updates[0].payload == {"knowledge": "Open daily 10-20", "knowledge_filename": "k.pdf"}

    r = client.post(
        f"/shops/{SHOP_ID}/knowledge",
        files={"file": ("k.pdf", b"%PDF-1.4 broken", "application/pdf")},
    )
    assert r.status_code == 400


# ── N-01 / FA-08: upload handlers are sync (FastAPI runs them in the threadpool) ──

UPLOAD_HANDLERS = (
    app.api.products.upload_product_image,
    app.api.products.import_preview,
    app.api.products.import_products,
    app.api.shops.upload_knowledge,
)


def test_f4_upload_handlers_sync_and_parsers_called(monkeypatch, client, user_db):
    for handler in UPLOAD_HANDLERS:
        assert not inspect.iscoroutinefunction(handler), handler.__name__

    calls = []

    def recording(func):
        def wrapper(*args):
            calls.append(func)
            if func is app.services.import_products.preview_file:
                return {"headers": []}
            raise ValueError("parser-called")
        return wrapper

    monkeypatch.setattr(app.api.shops, "extract_pdf_text", recording(pdf_extract.extract_pdf_text))
    monkeypatch.setattr(
        app.api.products, "preview_file", recording(app.services.import_products.preview_file)
    )
    monkeypatch.setattr(
        app.api.products,
        "parse_products_file",
        recording(app.services.import_products.parse_products_file),
    )
    for module in (app.api.shops, app.api.products):
        monkeypatch.setattr(module, "bulk_import_allowed", lambda tier: True)
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "pro"}]

    r = client.post(
        f"/shops/{SHOP_ID}/knowledge",
        files={"file": ("k.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 400 and r.json()["detail"] == "parser-called"

    r = client.post(
        "/products/import/preview",
        data={"shop_id": SHOP_ID},
        files={"file": ("p.csv", b"name,price\na,1\n", "text/csv")},
    )
    assert r.status_code == 200 and r.json() == {"headers": []}

    r = client.post(
        "/products/import",
        data={"shop_id": SHOP_ID},
        files={"file": ("p.csv", b"name,price\na,1\n", "text/csv")},
    )
    assert r.status_code == 400 and r.json()["detail"] == "parser-called"

    assert calls == [
        app.services.pdf_extract.extract_pdf_text,
        app.services.import_products.preview_file,
        app.services.import_products.parse_products_file,
    ]
