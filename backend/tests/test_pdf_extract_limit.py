"""S24-13: extract_pdf_text-ის შედეგი (suffix-ის ჩათვლით) არასოდეს აღემატება MAX_CHARS-ს —
იგივე რიცხვი, რაც DB-ის shops_knowledge_len_chk (0043)."""
from types import SimpleNamespace

import app.services.pdf_extract as pdf_extract

SUFFIX = "\n…(შემოკლებულია)"


def _fake_reader(monkeypatch, texts):
    pages = [SimpleNamespace(extract_text=lambda t=t: t) for t in texts]
    monkeypatch.setattr(pdf_extract, "PdfReader", lambda stream: SimpleNamespace(pages=pages))


def test_suffix_constant():
    assert pdf_extract.TRUNCATED_SUFFIX == SUFFIX
    assert pdf_extract.MAX_CHARS == 50_000


def test_over_limit_fits_max_chars_including_suffix(monkeypatch):
    _fake_reader(monkeypatch, ["a" * 60_000])
    result = pdf_extract.extract_pdf_text(b"%PDF")
    assert len(result) == pdf_extract.MAX_CHARS
    assert result.endswith(pdf_extract.TRUNCATED_SUFFIX)
    assert result == "a" * (pdf_extract.MAX_CHARS - len(SUFFIX)) + SUFFIX


def test_exactly_max_chars_unchanged(monkeypatch):
    _fake_reader(monkeypatch, ["a" * pdf_extract.MAX_CHARS])
    result = pdf_extract.extract_pdf_text(b"%PDF")
    assert result == "a" * pdf_extract.MAX_CHARS
    assert not result.endswith(SUFFIX)


def test_one_over_max_chars_fits(monkeypatch):
    _fake_reader(monkeypatch, ["a" * (pdf_extract.MAX_CHARS + 1)])
    result = pdf_extract.extract_pdf_text(b"%PDF")
    assert len(result) == pdf_extract.MAX_CHARS
    assert result.endswith(SUFFIX)


def test_multipage_over_limit_fits(monkeypatch):
    _fake_reader(monkeypatch, ["b" * 20_000] * 5)
    result = pdf_extract.extract_pdf_text(b"%PDF")
    assert len(result) == pdf_extract.MAX_CHARS
    assert result.endswith(SUFFIX)
