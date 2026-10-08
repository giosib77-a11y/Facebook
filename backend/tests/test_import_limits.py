"""B-2: xlsx import — სვეტების ჭერი და zip-bomb (გაშლილი ზომის) ჭერი."""
import io

import pytest
from openpyxl import Workbook

import app.services.import_products as imp


def _xlsx(cells: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    for ref, val in cells.items():
        ws[ref] = val
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_b2_wide_dimension_is_capped_to_max_cols():
    # უკიდურესი სვეტი XFD (16384) -> dimension A1:XFD2; ძველი კოდი 16384-სვეტიან მწკრივებს ქმნიდა
    content = _xlsx({"A1": "name", "B1": "price", "XFD1": "junk", "A2": "Shirt", "B2": 10})
    rows = imp.read_rows(content, "w.xlsx")
    assert all(len(r) <= imp.MAX_COLS for r in rows)
    products, errors = imp.parse_products_file(content, "w.xlsx")
    assert errors == []
    assert products[0]["name"] == "Shirt" and products[0]["price"] == 10.0


def test_b2_oversized_uncompressed_rejected(monkeypatch):
    content = _xlsx({"A1": "name", "A2": "x" * 5000})
    monkeypatch.setattr(imp, "MAX_UNCOMPRESSED_BYTES", 1000)
    with pytest.raises(ValueError, match="ძალიან დიდია"):
        imp.read_rows(content, "big.xlsx")


def test_b2_normal_file_under_size_limit_ok():
    content = _xlsx({"A1": "name", "A2": "Shirt"})
    assert imp.parse_products_file(content, "ok.xlsx")[0][0]["name"] == "Shirt"


def test_b2_non_zip_xlsx_gives_value_error():
    with pytest.raises(ValueError, match="Excel ფაილის გახსნა"):
        imp.read_rows(b"not a zip", "bad.xlsx")
