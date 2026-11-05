"""S21-7 (A-048): static guard for migration 0038 (llm_usage_by_model RPC). Reads the file only; no database."""

import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0038_llm_usage_by_model.sql"
SIGNATURE = "public.llm_usage_by_model(uuid, uuid, timestamptz)"


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def test_migration_0038_groups_usage_by_provider_and_model_with_empty_search_path():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "create or replace function public.llm_usage_by_model(p_owner uuid, p_shop uuid, p_since timestamptz)" in code
    assert (
        "returns table ( provider text, model text, input_tokens bigint, output_tokens bigint, "
        "cache_read_tokens bigint, cache_write_tokens bigint )"
    ) in code
    assert "language sql" in code and "stable" in code
    assert "set search_path = ''" in code
    assert "group by u.provider, u.model" in code
    assert "sum(u.input_tokens)::bigint" in code and "sum(u.cache_write_tokens)::bigint" in code
    assert "from public.llm_usage u" in code
    assert "u.created_at >= p_since" in code


def test_migration_0038_filters_by_shop_or_owner_or_whole_platform():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "(p_shop is null or u.shop_id = p_shop)" in code
    assert "u.shop_id in (select s.id from public.shops s where s.owner_id = p_owner)" in code
    assert "p_owner is null" in code


def test_migration_0038_is_invoker_and_only_service_role_can_execute():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "security definer" not in code  # INVOKER: service_role can already select llm_usage and shops
    assert "revoke execute on function public.llm_usage_by_model" in code
    assert "from public, anon, authenticated" in code
    assert "to authenticated" not in code and "to anon" not in code
    assert re.findall(r"\bgrant\b[^;]*;", code) == [
        f"grant execute on function {SIGNATURE} to service_role;"
    ]
    assert code.index("create or replace function") < code.index("revoke execute") < code.index("grant execute")
    assert code.count("begin;") == 1 and code.count("commit;") == 1


def test_migration_0038_has_no_destructive_statements_and_leaves_0035_alone():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    for forbidden in ("drop", "delete from", "truncate", "alter table", "create policy", "insert into", "update "):
        assert forbidden not in code, forbidden
    assert "llm_tokens_used" not in code


def test_migration_0038_documents_verification_rollback_and_deploy_order_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    assert "has_function_privilege('authenticated', 'public.llm_usage_by_model(uuid,uuid,timestamptz)', 'EXECUTE')" in comments
    assert "has_function_privilege('service_role', 'public.llm_usage_by_model(uuid,uuid,timestamptz)', 'EXECUTE')" in comments
    assert "public.llm_usage_by_model(null, null, date_trunc('month', now()))" in comments
    assert f"--   drop function if exists {SIGNATURE};" in sql
    assert "drop" in comments.lower() and "drop" not in _code(sql)
    assert "deploy" in comments.lower() and "PGRST202" in comments and "restart" in comments.lower()
