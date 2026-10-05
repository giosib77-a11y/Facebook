"""N-01 / N-02: heavy file parsing must not block the event loop and must be bounded."""
import uuid

import pytest

import app.api.products
import app.api.shops
import app.services.pdf_extract as pdf_extract

SHOP_ID = str(uuid.uuid4())
SUFFIX = "\n…(შემოკლებულია)"


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


# ── N-01: parsers run off the event loop ──

def test_f4_parsers_called_via_threadpool(monkeypatch, client, user_db):
    calls = []

    async def recording_threadpool(func, *args):
        calls.append(func)
        if func is app.services.import_products.preview_file:
            return {"headers": []}
        raise ValueError("parsed-in-threadpool")

    for module in (app.api.shops, app.api.products):
        monkeypatch.setattr(module, "run_in_threadpool", recording_threadpool)
        monkeypatch.setattr(module, "bulk_import_allowed", lambda tier: True)
    user_db.responses[("shops", "select")] = [{"id": SHOP_ID, "subscription_tier": "pro"}]

    r = client.post(
        f"/shops/{SHOP_ID}/knowledge",
        files={"file": ("k.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 400 and r.json()["detail"] == "parsed-in-threadpool"

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
    assert r.status_code == 400 and r.json()["detail"] == "parsed-in-threadpool"

    assert calls == [
        app.services.pdf_extract.extract_pdf_text,
        app.services.import_products.preview_file,
        app.services.import_products.parse_products_file,
    ]
