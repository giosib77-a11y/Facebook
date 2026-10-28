"""S14-4: usage normalization, llm_usage recording and the 0025 migration (static guard)."""
import logging
import re
from pathlib import Path
from types import SimpleNamespace

from app.services import llm
from tests.conftest import FakeSupabase

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0025_llm_usage.sql"


# ---------------------------------------------------------------------------
# normalization
# ---------------------------------------------------------------------------
def test_claude_usage_maps_all_four_counters():
    u = llm._claude_usage(SimpleNamespace(
        input_tokens=11, output_tokens=22, cache_read_input_tokens=33, cache_creation_input_tokens=44,
    ))
    assert u == llm.Usage(11, 22, 33, 44)


def test_claude_usage_none_and_missing_are_zero():
    assert llm._claude_usage(None) == llm.Usage(0, 0, 0, 0)
    assert llm._claude_usage(SimpleNamespace(input_tokens=5)) == llm.Usage(5, 0, 0, 0)
    u = llm._claude_usage(SimpleNamespace(
        input_tokens=None, output_tokens=7, cache_read_input_tokens=None, cache_creation_input_tokens=None,
    ))
    assert u == llm.Usage(0, 7, 0, 0)


def test_openai_usage_subtracts_cached_from_input():
    u = llm._openai_usage(SimpleNamespace(
        input_tokens=1500, output_tokens=80, input_tokens_details=SimpleNamespace(cached_tokens=1024),
    ))
    assert u == llm.Usage(input_tokens=476, output_tokens=80, cache_read_tokens=1024, cache_write_tokens=0)


def test_openai_usage_none_safe():
    assert llm._openai_usage(None) == llm.Usage(0, 0, 0, 0)
    assert llm._openai_usage(SimpleNamespace(input_tokens=10, output_tokens=2)) == llm.Usage(10, 2, 0, 0)
    u = llm._openai_usage(SimpleNamespace(
        input_tokens=10, output_tokens=None, input_tokens_details=SimpleNamespace(cached_tokens=None),
    ))
    assert u == llm.Usage(10, 0, 0, 0)


def test_usage_never_negative():
    # cached > input (inconsistent provider data) must not produce a negative input counter
    u = llm._openai_usage(SimpleNamespace(
        input_tokens=100, output_tokens=-5, input_tokens_details=SimpleNamespace(cached_tokens=300),
    ))
    assert u.input_tokens == 0 and u.output_tokens == 0 and u.cache_read_tokens == 300
    c = llm._claude_usage(SimpleNamespace(
        input_tokens=-1, output_tokens=-2, cache_read_input_tokens=-3, cache_creation_input_tokens=-4,
    ))
    assert c == llm.Usage(0, 0, 0, 0)


def test_non_numeric_counters_are_zero():
    c = llm._claude_usage(SimpleNamespace(
        input_tokens="12", output_tokens=True, cache_read_input_tokens=[], cache_creation_input_tokens=object(),
    ))
    assert c == llm.Usage(0, 0, 0, 0)


# ---------------------------------------------------------------------------
# record_usage
# ---------------------------------------------------------------------------
def _result():
    return llm.LLMResult("text", "claude", "claude-x", llm.Usage(1, 2, 3, 4))


def test_record_usage_inserts_all_fields(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(llm, "get_service_client", lambda: db)
    llm.record_usage("shop-uuid-1", _result())
    calls = db.calls_for("llm_usage", "insert")
    assert len(calls) == 1
    assert calls[0].payload == {
        "shop_id": "shop-uuid-1",
        "provider": "claude",
        "model": "claude-x",
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_read_tokens": 3,
        "cache_write_tokens": 4,
    }


def test_record_usage_db_error_logs_warning_and_does_not_raise(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    db = FakeSupabase()
    db.errors[("llm_usage", "insert")] = RuntimeError("db down")
    monkeypatch.setattr(llm, "get_service_client", lambda: db)
    llm.record_usage("shop-uuid-2", _result())  # must not raise
    rec = [r for r in caplog.records if "llm_usage write failed" in r.getMessage()]
    assert len(rec) == 1 and rec[0].levelno == logging.WARNING
    assert "shop-uuid-2" in rec[0].getMessage()
    assert rec[0].exc_info is not None


def test_record_usage_client_construction_error_does_not_raise(monkeypatch):
    def boom():
        raise RuntimeError("no supabase config")

    monkeypatch.setattr(llm, "get_service_client", boom)
    llm.record_usage("s", _result())


# ---------------------------------------------------------------------------
# migration static guard
# ---------------------------------------------------------------------------
def _sql_without_comments() -> str:
    text = MIGRATION.read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--")).lower()


def test_migration_is_backend_only():
    sql = _sql_without_comments()
    assert "enable row level security" in sql
    assert re.search(r"revoke all on table public\.llm_usage from public, anon, authenticated", sql)
    assert "create policy" not in sql
    assert re.search(r"grant select, insert on table public\.llm_usage to service_role", sql)
    assert not re.search(r"grant[^;]*\b(anon|authenticated)\b", sql)


def test_migration_shape():
    sql = _sql_without_comments()
    assert "create table if not exists public.llm_usage" in sql
    assert "references public.shops (id) on delete cascade" in sql
    assert "provider in ('claude', 'openai')" in sql
    assert sql.count(">= 0") == 4
    assert "create index if not exists llm_usage_shop_created_idx" in sql
