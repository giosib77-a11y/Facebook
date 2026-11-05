"""S22-3 (A-041): static guard for migration 0039 (admin_overview_stats / admin_growth / admin_shop_counts RPCs).
Reads the file only; no database."""

import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0039_admin_stats.sql"
SIGNATURES = (
    "public.admin_overview_stats()",
    "public.admin_growth(integer)",
    "public.admin_shop_counts()",
)


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def test_migration_0039_defines_three_stable_jsonb_functions_with_empty_search_path():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "create or replace function public.admin_overview_stats()" in code
    assert "create or replace function public.admin_growth(p_months integer)" in code
    assert "create or replace function public.admin_shop_counts()" in code
    assert code.count("create or replace function") == 3
    assert code.count("returns jsonb") == 3
    assert code.count("language sql") == 3 and code.count(" stable ") == 3
    assert code.count("set search_path = ''") == 3


def test_migration_0039_overview_matches_python_semantics():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    # revenue: everything except cancelled (a null status counts, like `o.get("status") != "cancelled"`)
    assert "status is distinct from 'cancelled'" in code
    assert "coalesce(sum(o.total), 0)" in code
    assert "count(distinct s.owner_id)" in code and "s.owner_id is not null" in code
    assert "coalesce(s.facebook_page_id, '') <> ''" in code
    assert "o.created_at >= now() - interval '30 days'" in code
    # highest tier per owner; unknown tier -> free (copy of core/tiers.best_tier)
    assert "array['free','basic','standard','business']" in code.replace(", ", ",")
    assert "array_position(" in code and "coalesce(array_position(" in code
    assert "max(" in code and "group by s.owner_id" in code
    for key in ("total_shops", "total_sellers", "connected_shops", "total_products", "total_orders",
                "orders_30d", "revenue", "owner_tiers"):
        assert f"'{key}'" in code, key
    assert "mrr" not in code  # MRR stays in Python (TIER_PRICES is the single source)


def test_migration_0039_growth_clamps_months_and_buckets_by_utc_month():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "greatest(1, least(coalesce(p_months, 6), 24))" in code
    assert "date_trunc('month', now() at time zone 'utc')" in code
    assert "make_interval(months =>" in code
    assert "to_char(s.created_at at time zone 'utc', 'yyyy-mm')" in code
    assert "to_char(o.created_at at time zone 'utc', 'yyyy-mm')" in code
    assert "'shops'" in code and "'orders'" in code


def test_migration_0039_shop_counts_cover_every_shop_and_current_month_customers():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "from public.shops s" in code
    assert code.count("left join") >= 3
    assert "group by shop_id" in code
    # same month formula as track_bot_customer (0004)
    assert "from public.bot_customers" in code
    assert "ym = to_char(now(), 'yyyy-mm')" in code
    assert "'{}'::jsonb" in code
    for key in ("'products'", "'orders'", "'customers'"):
        assert key in code, key


def test_migration_0039_is_invoker_and_only_service_role_can_execute():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "security definer" not in code  # INVOKER: service_role can already select all four tables
    assert code.count("revoke execute on function") == 3
    assert code.count("from public, anon, authenticated;") == 3
    assert code.count("to service_role;") == 3
    assert "to authenticated" not in code and "to anon" not in code
    assert re.findall(r"\bgrant\b[^;]*;", code) == [
        f"grant execute on function {sig} to service_role;" for sig in SIGNATURES
    ]
    for sig in SIGNATURES:
        assert f"revoke execute on function {sig} from public, anon, authenticated;" in code, sig
    # every function is created before the first revoke / grant
    assert code.rindex("create or replace function") < code.index("revoke execute") < code.index("grant execute")
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.index("begin;") < code.index("create or replace function")
    assert code.rindex("grant execute") < code.index("commit;")


def test_migration_0039_has_no_destructive_or_writing_statements():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    for forbidden in ("drop ", "create table", "delete from", "truncate", "alter table", "create policy",
                      "update public.", "insert into"):
        assert forbidden not in code, forbidden


def test_migration_0039_documents_verification_rollback_and_deploy_order_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    for sig in ("public.admin_overview_stats()", "public.admin_growth(integer)", "public.admin_shop_counts()"):
        assert f"has_function_privilege('authenticated', '{sig}', 'EXECUTE')" in comments, sig
        assert f"has_function_privilege('service_role', '{sig}', 'EXECUTE')" in comments, sig
        assert f"--   drop function if exists {sig};" in sql, sig
    assert "select public.admin_overview_stats();" in comments
    assert "select public.admin_growth(6);" in comments
    assert "jsonb_object_keys(public.admin_shop_counts())" in comments
    assert "drop" in comments.lower() and "drop " not in _code(sql)
    assert "deploy" in comments.lower() and "WARNING" in comments and "restart" in comments.lower()
