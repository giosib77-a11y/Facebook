"""scripts/backfill_image_descriptions.py: offline, fake service client, fake vision / LLM / download."""
import pytest
from postgrest.exceptions import APIError

from app.config import get_settings
from app.services import facebook, llm, vision
from scripts import backfill_image_descriptions as bf
from tests.conftest import FakeSupabase

BASE = "https://proj.supabase.co"
SHOP = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_SHOP = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SECRET_NAME = "Secret Product Name"
SECRET_DESC = "EN: secret description text"


def _url(shop, name="a.jpg"):
    return f"{BASE}/storage/v1/object/public/product-images/{shop}/{name}"


def _row(i, shop=SHOP, url="own", desc=None):
    return {
        "id": f"p{i}", "shop_id": shop, "name": SECRET_NAME,
        "image_url": _url(shop, f"{i}.jpg") if url == "own" else url,
        "image_description": desc,
    }


class Env:
    def __init__(self, monkeypatch):
        self.mp = monkeypatch
        self.db = FakeSupabase()
        self.sleeps = []
        self.described = []
        self.results = {}  # product-photo url -> description | None
        monkeypatch.setattr(get_settings(), "supabase_url", BASE)
        monkeypatch.setattr(bf, "get_service_client", lambda: self.db)
        monkeypatch.setattr(bf.time, "sleep", lambda s: self.sleeps.append(s))
        monkeypatch.setattr(vision, "describe_product_image", self._describe)

    def _describe(self, shop_id, url):
        self.described.append((shop_id, url))
        return self.results.get(url, SECRET_DESC)

    def rows(self, *rows):
        self.db.responses[("products", "select")] = list(rows)

    def updates(self):
        return self.db.calls_for("products", "update")


@pytest.fixture
def env(monkeypatch):
    return Env(monkeypatch)


def test_dry_run_touches_nothing(env, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("must not be called in --dry-run")
    monkeypatch.setattr(vision, "describe_product_image", boom)
    monkeypatch.setattr(facebook, "download_image", boom)
    monkeypatch.setattr(llm, "complete", boom)
    env.rows(_row(1), _row(2))
    assert bf.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "2 in total" in out and "estimate" in out
    assert "p1" in out and "p2" in out
    assert env.updates() == []


def test_dry_run_needs_no_key(env, monkeypatch, capsys):
    monkeypatch.setattr(bf, "get_settings", lambda: get_settings().model_copy(update={"anthropic_api_key": ""}))
    env.rows(_row(1))
    assert bf.main(["--dry-run"]) == 0


def test_missing_key_exits_2_before_db(env, monkeypatch, capsys):
    monkeypatch.setattr(bf, "get_settings", lambda: get_settings().model_copy(update={"anthropic_api_key": ""}))
    env.rows(_row(1))
    assert bf.main([]) == 2
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY is not set" in err
    assert env.db.calls == [] and env.described == []


def test_filter_skips_non_candidates(env, capsys):
    env.rows(
        _row(1, desc="already described"),
        _row(2, desc="   "),  # whitespace = empty -> candidate
        _row(3, url=None),
        _row(4, url="https://evil.example/x.jpg"),
        _row(5, url=_url(OTHER_SHOP)),  # another shop's folder
        _row(6),
    )
    assert bf.main(["--delay", "0"]) == 0
    assert [u for _, u in env.described] == [_url(SHOP, "2.jpg"), _url(SHOP, "6.jpg")]


def test_shop_filter_and_limit(env):
    env.rows(_row(1), _row(2), _row(3))
    assert bf.main(["--shop", SHOP.upper(), "--limit", "2", "--delay", "0"]) == 0
    select = env.db  # the select is the first executed call
    assert ("eq", "shop_id", SHOP) in select.calls[0].filters
    assert len(env.described) == 2
    assert len(env.updates()) == 2


def test_save_payload_and_filters(env, capsys):
    env.rows(_row(1))
    assert bf.main(["--delay", "0"]) == 0
    (upd,) = env.updates()
    assert upd.payload == {"image_description": SECRET_DESC}
    assert ("eq", "id", "p1") in upd.filters
    assert ("eq", "shop_id", SHOP) in upd.filters
    assert ("eq", "image_url", _url(SHOP, "1.jpg")) in upd.filters
    assert "1 saved, 0 failed" in capsys.readouterr().out


def test_failed_description_is_counted_and_run_continues(env, capsys):
    env.rows(_row(1), _row(2))
    env.results[_url(SHOP, "1.jpg")] = None
    assert bf.main(["--delay", "0"]) == 0
    assert len(env.described) == 2
    assert len(env.updates()) == 1
    out = capsys.readouterr().out
    assert "failed: p1" in out and "1 saved, 1 failed" in out


@pytest.mark.parametrize("code,expected", [("PGRST204", 2), ("42703", 2), ("XX000", 1)])
def test_select_error(env, capsys, code, expected):
    class Err(Exception):
        pass
    exc = Err("column products.image_description does not exist")
    exc.code = code
    env.db.errors[("products", "select")] = exc
    assert bf.main(["--dry-run"]) == (2 if code != "XX000" else 1)
    err = capsys.readouterr().err
    if expected == 2:
        assert "0028" in err
    else:
        assert "0028" not in err and "Err" in err


def test_idempotent_second_run(env, capsys):
    env.rows(_row(1, desc="done"), _row(2, desc="done"))
    assert bf.main(["--delay", "0"]) == 0
    assert env.described == [] and env.updates() == []
    assert "0 in total" in capsys.readouterr().out


def test_delay_between_calls_only(env):
    env.rows(_row(1), _row(2), _row(3))
    assert bf.main(["--delay", "2.5"]) == 0
    assert env.sleeps == [2.5, 2.5]


def test_no_names_urls_or_descriptions_printed(env, capsys):
    env.rows(_row(1), _row(2, url="https://evil.example/x.jpg"))
    env.results[_url(SHOP, "1.jpg")] = None
    bf.main(["--delay", "0"])
    env.results[_url(SHOP, "1.jpg")] = SECRET_DESC
    bf.main(["--delay", "0"])
    captured = capsys.readouterr()
    text = captured.out + captured.err
    for secret in (SECRET_NAME, "supabase.co", "evil.example", SECRET_DESC, "secret description"):
        assert secret not in text


@pytest.mark.parametrize("args", [
    ["--limit", "0"], ["--limit", "501"], ["--limit", "x"], ["--shop", "not-a-uuid"],
    ["--delay", "-1"], ["--delay", "61"],
])
def test_bad_arguments_exit_2(env, args):
    assert bf.main(args) == 2
    assert env.db.calls == []


def test_keyboard_interrupt_exits_130(env, monkeypatch, capsys):
    env.rows(_row(1), _row(2))
    calls = []

    def describe(shop_id, url):
        calls.append(url)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return SECRET_DESC
    monkeypatch.setattr(vision, "describe_product_image", describe)
    assert bf.main(["--delay", "0"]) == 130
    assert "interrupted: 1 saved, 0 failed" in capsys.readouterr().out


def test_save_failure_counts_as_failed(env, capsys):
    env.rows(_row(1))
    env.db.errors[("products", "update")] = RuntimeError("db down")
    assert bf.main(["--delay", "0"]) == 0
    assert "0 saved, 1 failed" in capsys.readouterr().out


def test_save_schema_error_does_not_stop_the_run(env, capsys):
    """Stage 24: no global "migration 0028 missing" switch - every photo is tried and counted as failed."""
    env.rows(_row(1), _row(2))
    env.db.errors[("products", "update")] = APIError({
        "code": "42703", "message": 'column "image_description" of relation "products" does not exist',
        "details": None, "hint": None,
    })
    assert bf.main(["--delay", "0"]) == 0
    assert len(env.described) == 2 and len(env.updates()) == 2
    out = capsys.readouterr().out
    assert "0 saved, 2 failed" in out
    assert not hasattr(vision, "descriptions_enabled")


def test_cost_estimate_uses_provider_prices():
    # 10 photos x (2000 x 0.10 + 300 x 0.50) / 1e6
    assert bf.estimate_usd("claude", 10) == pytest.approx(10 * (200 + 150) / 1e6)
