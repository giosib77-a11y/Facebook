"""S20-8: static guard for migration 0035 (llm_tokens_used RPC + llm_usage index). Reads the file only; no database."""

import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0035_llm_usage_budget.sql"
SIGNATURE = "public.llm_tokens_used(uuid, timestamptz)"


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def test_migration_0035_function_sums_all_four_token_columns_with_empty_search_path():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "create or replace function public.llm_tokens_used(p_owner uuid, p_since timestamptz)" in code
    assert "returns bigint" in code
    assert "language sql" in code and "stable" in code
    assert "set search_path = ''" in code
    assert "security definer" not in code  # INVOKER: service_role can already select llm_usage and shops
    assert "u.input_tokens + u.output_tokens + u.cache_read_tokens + u.cache_write_tokens" in code
    assert "coalesce(sum(" in code and ")::bigint" in code
    assert "u.created_at >= p_since" in code
    # null owner = whole platform, otherwise only that owner's shops; every object schema-qualified
    assert "p_owner is null" in code
    assert "u.shop_id in (select s.id from public.shops s where s.owner_id = p_owner)" in code
    assert "from public.llm_usage u" in code


def test_migration_0035_adds_the_created_at_index_idempotently():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "create index if not exists llm_usage_created_idx on public.llm_usage (created_at);" in code


def test_migration_0035_revokes_everyone_and_grants_only_service_role():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "revoke execute on function public.llm_tokens_used" in code
    assert "from public, anon, authenticated" in code
    assert re.search(r"\bgrant\b[^;]*\bto\s+(public|anon|authenticated)\b", code) is None
    assert re.findall(r"\bgrant\b[^;]*;", code) == [
        f"grant execute on function {SIGNATURE} to service_role;"
    ]
    assert code.index("create or replace function") < code.index("revoke execute") < code.index("grant execute")
    assert code.count("begin;") == 1 and code.count("commit;") == 1


def test_migration_0035_has_no_destructive_statements():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    for forbidden in ("drop ", "delete from", "truncate", "alter table", "create policy", "insert into", "update "):
        assert forbidden not in code, forbidden


def test_migration_0035_documents_verification_rollback_and_deploy_order_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    assert "has_function_privilege('authenticated', 'public.llm_tokens_used(uuid,timestamptz)', 'EXECUTE')" in comments
    assert "has_function_privilege('service_role', 'public.llm_tokens_used(uuid,timestamptz)', 'EXECUTE')" in comments
    assert "select public.llm_tokens_used(null, date_trunc('month', now()))" in comments
    assert f"--   drop function if exists {SIGNATURE};" in sql
    assert "--   drop index if exists public.llm_usage_created_idx;" in sql
    assert "drop" in comments.lower() and "drop" not in _code(sql)
    assert "deploy" in comments.lower() and "PGRST202" in comments
