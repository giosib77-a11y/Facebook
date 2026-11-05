"""S22-5 (A-041): static guard for migration 0040 (pg_trgm guard, products trigram indexes, search_products RPC).
Reads the file only; no database."""

import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0040_products_search_trgm.sql"
SIGNATURE = "public.search_products(uuid, text[], text, integer)"
GUARD = "if not exists (select 1 from pg_catalog.pg_extension where extname = 'pg_trgm') then"


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def _inside_guard(code: str, pos: int) -> bool:
    start = code.rfind(GUARD, 0, pos)
    return start != -1 and "end if;" not in code[start:pos]


def test_migration_0040_file_exists():
    assert MIGRATION.is_file()


def test_migration_0040_creates_pg_trgm_only_inside_guard_in_extensions_schema():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    positions = [m.start() for m in re.finditer(r"create extension", code)]
    assert len(positions) == 1
    assert _inside_guard(code, positions[0])
    assert "create extension pg_trgm with schema extensions;" in code
    # Supabase's extension event triggers break an unguarded `create extension if not exists` (2BP01, see 0034)
    assert "create extension if not exists pg_trgm" not in code
    assert "drop extension" not in code


def test_migration_0040_raises_when_pg_trgm_lives_in_another_schema():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "pg_catalog.pg_namespace" in code and "extnamespace" in code
    assert "raise exception 'pg_trgm is installed in schema %, expected extensions" in code
    assert "is distinct from 'extensions'" in code
    # the check runs after the (guarded) create, inside the same DO block, before any index / function
    assert code.index("create extension") < code.index("raise exception") < code.index("create index")
    assert code.index("raise exception") < code.index("create or replace function")
    do_start = code.index("do $$")
    do_end = code.index("end $$;")
    assert do_start < code.index("create extension") < code.index("raise exception") < do_end


def test_migration_0040_creates_two_idempotent_gin_trigram_indexes():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert code.count("create index if not exists") == 2
    assert "create index if not exists products_name_trgm_idx on public.products using gin (name extensions.gin_trgm_ops);" in code
    assert (
        "create index if not exists products_description_trgm_idx on public.products "
        "using gin (description extensions.gin_trgm_ops);" in code
    )
    assert code.count("gin_trgm_ops") == 2
    assert "create unique index" not in code


def test_migration_0040_function_signature_columns_and_attributes():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert code.count("create or replace function") == 1
    assert (
        "create or replace function public.search_products(p_shop uuid, p_terms text[], p_query text, p_limit integer)"
        in code
    )
    assert (
        "returns table (id uuid, name text, price numeric, quantity integer, sku text, description text, score integer)"
        in code
    )
    assert "language sql" in code and " stable " in code
    assert "set search_path = ''" in code


def test_migration_0040_is_tenant_scoped_and_active_only_in_sql():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "p.shop_id = p_shop" in code
    assert "p.is_active" in code
    assert "from public.products p" in code


def test_migration_0040_terms_are_filtered_capped_and_escaped():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "unnest(coalesce(p_terms, '{}'::text[]))" in code
    assert "char_length(u.term) between 2 and 50" in code
    assert "select distinct" in code and "limit 8" in code
    # LIKE metacharacters in a term are escaped: backslash first, then % and _
    assert "replace(replace(replace(t.term, '\\', '\\\\'), '%', '\\%'), '_', '\\_')" in code
    assert "'%' || replace(" in code and "|| '%'" in code
    assert "ilike any(" in code
    for column in ("p.name", "p.description", "p.sku", "p.image_description"):
        assert f"{column} ilike" in code, column


def test_migration_0040_any_uses_array_column_not_double_parenthesised_subquery():
    # S22-10: `x ilike any((select arr from pats))` is parsed by Postgres as the subquery form ANY (subquery)
    # (text ~~* text[] -> "operator does not exist"), so CREATE FUNCTION fails. The array must come from a column.
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "any((select" not in code
    assert "cross join pats" in code
    assert code.count("any(pats.arr)") == 4
    assert "unnest(pats.arr)" in code
    assert "(select arr from pats)" not in code


def test_migration_0040_scores_by_matched_terms_and_uses_similarity_only_as_tie_break():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "count(*)" in code and "::integer" in code
    order = code[code.index("order by m.score desc"):]
    assert order.startswith("order by m.score desc, extensions.similarity(m.name, coalesce(p_query, '')) desc, m.id")
    assert "extensions.similarity(" in code
    # the row filter is term matching, never a similarity threshold
    assert "similarity(" not in code[: code.index("order by m.score desc")]
    assert "extensions.word_similarity" not in code and " % " not in code


def test_migration_0040_limit_is_clamped_to_1_20_default_10():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "limit greatest(1, least(coalesce(p_limit, 10), 20))" in code


def test_migration_0040_is_invoker_and_only_service_role_can_execute():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "security definer" not in code
    assert code.count("revoke execute on function") == 1
    assert f"revoke execute on function {SIGNATURE} from public, anon, authenticated;" in code
    assert re.findall(r"\bgrant\b[^;]*;", code) == [f"grant execute on function {SIGNATURE} to service_role;"]
    assert "to authenticated" not in code and "to anon" not in code
    assert code.rindex("create or replace function") < code.index("revoke execute") < code.index("grant execute")
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.index("begin;") < code.index("do $$")
    assert code.rindex("grant execute") < code.index("commit;")


def test_migration_0040_has_no_destructive_or_writing_statements():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    for forbidden in ("drop ", "create table", "delete from", "truncate", "alter table", "create policy",
                      "update public.", "insert into"):
        assert forbidden not in code, forbidden


def test_migration_0040_documents_verification_rollback_and_deploy_order_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    assert f"has_function_privilege('authenticated', '{SIGNATURE}', 'EXECUTE')" in comments
    assert f"has_function_privilege('service_role', '{SIGNATURE}', 'EXECUTE')" in comments
    assert "pg_extension" in comments and "pg_indexes" in comments
    assert "public.search_products((select id from public.shops limit 1), array['test'], 'test', 5)" in comments
    assert f"--   drop function if exists {SIGNATURE};" in sql
    assert "--   drop index if exists public.products_name_trgm_idx;" in sql
    assert "--   drop index if exists public.products_description_trgm_idx;" in sql
    assert "drop " not in _code(sql)
    assert "0028" in comments and "deploy" in comments.lower() and "WARNING" in comments
    assert "restart" in comments.lower()
