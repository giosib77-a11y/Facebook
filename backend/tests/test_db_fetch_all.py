"""Stage 22 (S22-1, A-041): core/db.fetch_all + FakeSupabase-ის range / order / 1000-იანი ჭერი."""
import logging

import pytest
from fastapi import HTTPException
from postgrest.exceptions import APIError

from app.core.db import PAGE_SIZE, TooManyRows, fetch_all, run

from tests.conftest import FakeSupabase


def _rows(n):
    return [{"id": i} for i in range(n)]


def _db(n):
    db = FakeSupabase()
    db.responses[("products", "select")] = _rows(n)
    return db


def _factory(db):
    return lambda: db.table("products").select("id").order("id")


def test_fetch_all_reads_past_first_page():
    db = _db(2500)
    out = fetch_all(_factory(db), max_rows=10_000, label="t")
    assert len(out) == 2500
    assert out[0] == {"id": 0} and out[-1] == {"id": 2499}
    calls = db.calls_for("products", "select")
    assert [c.range_ for c in calls] == [(0, 999), (1000, 1999), (2000, 2999)]


def test_fetch_all_exactly_one_full_page_needs_second_empty_query():
    db = _db(1000)
    out = fetch_all(_factory(db), max_rows=10_000, label="t")
    assert len(out) == 1000
    calls = db.calls_for("products", "select")
    assert [c.range_ for c in calls] == [(0, 999), (1000, 1999)]


def test_fetch_all_short_first_page_is_one_query():
    db = _db(3)
    assert fetch_all(_factory(db), max_rows=10_000, label="t") == _rows(3)
    assert len(db.calls_for("products", "select")) == 1


def test_fetch_all_builds_fresh_query_per_page():
    db = _db(2500)
    built = []

    def make():
        q = db.table("products").select("id").order("id")
        built.append(q)
        return q

    fetch_all(make, max_rows=10_000, label="t")
    assert len(built) == 3
    assert len({id(q) for q in built}) == 3
    assert PAGE_SIZE == 1000


def test_fetch_all_truncates_at_max_rows_and_warns(caplog):
    db = _db(2500)
    with caplog.at_level(logging.WARNING, logger="app"):
        out = fetch_all(_factory(db), max_rows=1500, label="bot products")
    assert len(out) == 1500
    calls = db.calls_for("products", "select")
    assert calls[-1].range_ == (1000, 1500)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "bot products" in msg and "1500" in msg
    assert "'id'" not in msg and "{" not in msg  # მწკრივის მონაცემი ლოგში არ არის


def test_fetch_all_strict_raises_too_many_rows():
    db = _db(2500)
    with pytest.raises(TooManyRows) as exc:
        fetch_all(_factory(db), max_rows=1500, label="export", strict=True)
    assert exc.value.label == "export"
    assert exc.value.max_rows == 1500


def test_fetch_all_strict_ok_when_exactly_max_rows():
    db = _db(1500)
    assert len(fetch_all(_factory(db), max_rows=1500, label="t", strict=True)) == 1500


def test_fetch_all_execute_run_preserves_http_errors():
    db = _db(5)
    db.errors[("products", "select")] = APIError(
        {"message": "denied", "code": "42501", "details": None, "hint": None}
    )
    with pytest.raises(HTTPException) as exc:
        fetch_all(_factory(db), max_rows=100, label="t", execute=run)
    assert exc.value.status_code == 403


def test_fetch_all_none_data_is_empty_list():
    db = FakeSupabase()
    db.responses[("products", "select")] = None
    assert fetch_all(_factory(db), max_rows=100, label="t") == []


def test_fetch_all_custom_page_size():
    db = _db(25)
    out = fetch_all(_factory(db), max_rows=100, label="t", page_size=10)
    assert len(out) == 25
    assert [c.range_ for c in db.calls_for("products", "select")] == [(0, 9), (10, 19), (20, 29)]


@pytest.mark.parametrize("kwargs", [{"max_rows": 0}, {"max_rows": -1}, {"max_rows": 5, "page_size": 0}])
def test_fetch_all_rejects_bad_limits(kwargs):
    db = _db(3)
    with pytest.raises(ValueError):
        fetch_all(_factory(db), label="t", **kwargs)
    assert db.calls == []


# ---- fake-ის თვითშემოწმება ----

def test_fake_range_twice_on_one_query_asserts():
    db = _db(10)
    q = db.table("products").select("id").range(0, 4)
    with pytest.raises(AssertionError, match="range\\(\\) called twice"):
        q.range(5, 9)


def test_fake_caps_select_without_range_at_1000():
    db = _db(2500)
    res = db.table("products").select("id").execute()
    assert len(res.data) == 1000


def test_fake_range_page_is_also_capped():
    db = _db(2500)
    res = db.table("products").select("id").range(0, 1999).execute()
    assert len(res.data) == 1000


def test_fake_records_orders():
    db = _db(1)
    q = db.table("products").select("id").order("created_at", desc=True).order("id")
    assert q.orders == [("created_at", True), ("id", False)]
