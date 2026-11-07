"""Stage 22 (S22-6, A-041): search_products tool დიდ კატალოგზე — Postgres (RPC 0040), პატარაზე — მეხსიერება."""
import logging
import uuid

import pytest

from app.config import get_settings
from app.services import product_search, prompt, tools
from app.services.tools import ToolContext, execute

SHOP_ID = str(uuid.uuid4())
SHOP = {"id": SHOP_ID, "name": "Big Store", "currency": "GEL"}
SECRET_QUERY = "sekretuli-nacarmi-kveri"


class RpcError(Exception):
    def __init__(self, code):
        super().__init__(f"rpc error {code}")
        self.code = code


def catalogue(n: int) -> list[dict]:
    return [{"id": f"{i:05d}", "name": f"Item {i}", "price": 5, "quantity": 1} for i in range(n)]


def ctx(n: int = 300, shop: dict = SHOP) -> ToolContext:
    products = catalogue(n)
    products[0] = {"id": "00000", "name": "Red shirt", "price": 89, "quantity": 3, "sku": "RS1", "description": "cotton"}
    return ToolContext(shop=shop, products=products)


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    product_search._reset_for_tests()
    monkeypatch.setattr(get_settings(), "bot_db_search_min_products", 300)
    yield
    product_search._reset_for_tests()


@pytest.fixture
def db(service_db, monkeypatch):
    monkeypatch.setattr(product_search, "get_service_client", lambda: service_db)
    return service_db


def run(query: str, c: ToolContext | None = None) -> str:
    out = execute("search_products", {"query": query}, c or ctx())
    assert not out.is_error, out.content
    return out.content


def row(**kw) -> dict:
    base = {"id": "r1", "name": "Postgres hit", "price": 42, "quantity": 7, "sku": "PG1",
            "description": "from the database", "score": 2}
    base.update(kw)
    return base


def test_big_catalogue_searches_postgres(db):
    db.rpc_responses["search_products"] = [row()]
    out = run("red shirt")
    assert "Postgres hit" in out
    assert "Red shirt" not in out  # the in-memory match was not used
    assert len(db.rpc_calls) == 1
    call = db.rpc_calls[0]
    assert call.fn == "search_products"
    assert call.params == {
        "p_shop": SHOP_ID,
        "p_terms": sorted(prompt.query_tokens("red shirt")),
        "p_query": "red shirt",
        "p_limit": 10,
    }


def test_small_catalogue_stays_in_memory(db):
    out = run("red shirt", ctx(299))
    assert db.rpc_calls == []
    assert out == (
        'Products matching "red shirt" (1 of 299 in the catalogue):\n'
        "- Red shirt — 89 GEL, in stock: 3, SKU: RS1. cotton"
    )


@pytest.mark.parametrize("n", [300, 5000])
def test_setting_zero_disables_postgres(db, monkeypatch, n):
    monkeypatch.setattr(get_settings(), "bot_db_search_min_products", 0)
    out = run("red shirt", ctx(n))
    assert db.rpc_calls == []
    assert "Red shirt" in out


def test_threshold_is_configurable(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "bot_db_search_min_products", 50)
    db.rpc_responses["search_products"] = [row()]
    assert "Postgres hit" in run("red shirt", ctx(50))
    assert len(db.rpc_calls) == 1


def test_missing_function_is_a_logged_rpc_error_without_backoff(db, monkeypatch, caplog):
    clock = [1000.0]
    monkeypatch.setattr(product_search, "_now", lambda: clock[0])
    db.rpc_errors["search_products"] = RpcError("PGRST202")
    with caplog.at_level(logging.DEBUG):
        out = run("red shirt")
        assert "Red shirt" in out  # in-memory result
        assert len(db.rpc_calls) == 1
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == ["search_products RPC failed (RpcError) - in-memory search"]

        clock[0] += 1  # no backoff: the very next search tries the RPC again; the WARNING is throttled (60 s)
        assert "Red shirt" in run("red shirt")
        assert len(db.rpc_calls) == 2

        db.rpc_errors.clear()  # the function appears - used on the next call, no restart and no waiting
        db.rpc_responses["search_products"] = [row()]
        clock[0] += 1
        assert "Postgres hit" in run("red shirt")
        assert len(db.rpc_calls) == 3

        db.rpc_errors["search_products"] = RpcError("42883")
        clock[0] += 61  # past the throttle window: WARNING again
        assert "Red shirt" in run("red shirt")
        assert len(db.rpc_calls) == 4
    assert sum(r.levelno == logging.WARNING for r in caplog.records) == 2
    assert "migration" not in caplog.text and "not applied" not in caplog.text


def test_other_error_falls_back_and_logs_class_only(db, monkeypatch, caplog):
    clock = [1000.0]
    monkeypatch.setattr(product_search, "_now", lambda: clock[0])
    db.rpc_errors["search_products"] = RuntimeError(f"boom {SECRET_QUERY}")
    with caplog.at_level(logging.DEBUG):
        out = run(f"red shirt {SECRET_QUERY}")
        assert "Red shirt" in out
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "RuntimeError" in warnings[0].getMessage()

        clock[0] += 10  # inside 60 s: RPC is retried (no backoff), WARNING is not repeated
        run("red shirt")
        assert len(db.rpc_calls) == 2
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

        clock[0] += 60
        run("red shirt")
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2
    text = " ".join(r.getMessage() for r in caplog.records)
    assert SECRET_QUERY not in text and "shirt" not in text.lower()


def test_non_list_response_falls_back(db):
    db.rpc_responses["search_products"] = {"unexpected": "dict"}
    assert "Red shirt" in run("red shirt")
    assert len(db.rpc_calls) == 1


def test_shop_id_is_never_a_tool_argument(db):
    db.rpc_responses["search_products"] = [row()]
    out = execute("search_products", {"query": "x", "shop_id": "other"}, ctx())
    assert out.is_error and out.content == "Error: invalid arguments for search_products."
    assert db.rpc_calls == []


def test_shop_id_comes_only_from_the_context(db):
    other = {"id": "11111111-1111-1111-1111-111111111111", "currency": "USD"}
    db.rpc_responses["search_products"] = [row()]
    out = run("red shirt", ctx(300, other))
    assert db.rpc_calls[0].params["p_shop"] == other["id"]
    assert "42 USD" in out


def test_shop_without_id_never_calls_rpc(db):
    run("red shirt", ctx(300, {"currency": "GEL"}))
    assert db.rpc_calls == []


def test_only_stopwords_skip_the_rpc(db):
    db.rpc_responses["search_products"] = [row()]
    out = run("მინდა გაქვთ")
    assert db.rpc_calls == []
    assert out == 'No products match "მინდა გაქვთ". The catalogue has 300 products.'


def test_empty_rpc_result(db):
    db.rpc_responses["search_products"] = []
    assert run("zzz-nothing") == 'No products match "zzz-nothing". The catalogue has 300 products.'
    assert len(db.rpc_calls) == 1


def test_rpc_rows_are_formatted_like_memory_rows(db):
    r = row()
    db.rpc_responses["search_products"] = [r, row(id="r2", name="Free item", price=0, quantity=0, sku=None,
                                                  description=None)]
    out = run("red shirt")
    assert out == (
        'Products matching "red shirt" (2 of 300 in the catalogue):\n'
        f"{prompt.product_line(r, 'GEL')}\n"
        "- Free item — price on request, out of stock"
    )
    assert "- Postgres hit — 42 GEL, in stock: 7, SKU: PG1. from the database" in out


def test_terms_are_capped_and_long_tokens_dropped(db):
    db.rpc_responses["search_products"] = []
    words = [f"word{i}" for i in range(12)]
    run(" ".join(words) + " " + "x" * 51)
    terms = db.rpc_calls[0].params["p_terms"]
    assert len(terms) == 8
    assert terms == sorted(terms)
    assert all(2 <= len(t) <= 50 for t in terms)


def test_successful_search_logs_no_query(db, caplog):
    db.rpc_responses["search_products"] = [row()]
    with caplog.at_level(logging.DEBUG):
        run(SECRET_QUERY)
    assert SECRET_QUERY not in " ".join(r.getMessage() for r in caplog.records)


def test_tools_module_does_not_name_the_db_client():
    from pathlib import Path
    src = Path(tools.__file__).read_text(encoding="utf-8")
    assert "get_service_client" not in src and "supabase" not in src
