"""S20-6: static guard for migration 0034 (subscriptions + backfill + daily pg_cron). Reads the file only; no database."""

import re
from pathlib import Path

from app.core.tiers import TIER_LIMITS

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0034_subscriptions.sql"


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def _code_of_migration() -> str:
    return _code(MIGRATION.read_text(encoding="utf-8"))


def test_migration_0034_table_is_idempotent_with_fk_and_tier_check():
    code = _code_of_migration()
    assert "create table if not exists public.subscriptions" in code
    assert "owner_id uuid primary key references auth.users (id) on delete cascade" in code
    assert "tier text not null default 'free'" in code
    assert "check (tier in ('free', 'basic', 'standard', 'business'))" in code
    assert "paid_until timestamptz" in code
    assert "updated_at timestamptz not null default now()" in code
    assert code.count("begin;") == 1 and code.count("commit;") == 1


def test_migration_0034_rls_owner_read_only_and_service_role_writes():
    code = _code_of_migration()
    assert "alter table public.subscriptions enable row level security" in code
    assert "drop policy if exists subscriptions_owner_read on public.subscriptions" in code
    assert "create policy subscriptions_owner_read on public.subscriptions" in code
    assert code.count("create policy") == 1
    assert "for select to authenticated" in code
    assert "using (owner_id = (select auth.uid()))" in code
    assert "revoke all on table public.subscriptions from public, anon, authenticated;" in code
    assert "grant select on table public.subscriptions to authenticated;" in code
    assert "grant select, insert, update on table public.subscriptions to service_role;" in code
    # authenticated / anon / public never get write privileges
    assert re.search(r"\bgrant\s+(insert|update|delete|all)\b[^;]*\bto\s+[^;]*\b(authenticated|anon|public)\b", code) is None
    assert re.search(r"\bgrant\b[^;]*\bto\s+(anon|public)\b", code) is None
    # revoke precedes the grants
    assert code.index("revoke all on table") < code.index("grant select on table")


def test_migration_0034_backfill_is_idempotent_30_days_for_paid_owners():
    code = _code_of_migration()
    assert "insert into public.subscriptions (owner_id, tier, paid_until)" in code
    assert "now() + interval '30 days'" in code
    assert "subscription_tier in ('basic', 'standard', 'business')" in code
    assert "owner_id is not null" in code
    assert "group by owner_id" in code
    assert "on conflict (owner_id) do nothing" in code
    # highest tier per owner
    assert "array_position(array['free', 'basic', 'standard', 'business'], subscription_tier) desc" in code


def test_migration_0034_expire_function_is_invoker_and_locked_down():
    code = _code_of_migration()
    assert "create or replace function public.expire_subscriptions() returns integer" in code
    assert "set search_path = ''" in code
    assert "security definer" not in code
    assert "revoke execute on function public.expire_subscriptions() from public, anon, authenticated;" in code
    # no grant of execute to anyone
    assert "grant execute" not in code
    assert code.index("create or replace function") < code.index("revoke execute")


def test_migration_0034_expire_function_downgrades_subscription_mirror_and_bots():
    code = _code_of_migration()
    # expiry: only paid, dated, past-due rows; becomes free with no deadline
    assert (
        "update public.subscriptions set tier = 'free', paid_until = null, updated_at = now() "
        "where tier <> 'free' and paid_until is not null and paid_until < now() returning owner_id"
    ) in code
    assert "array_agg(owner_id) into v_owners" in code
    assert "if v_owners is null then return 0;" in code
    # mirror on shops only for the expired owners
    assert "update public.shops set subscription_tier = 'free' where owner_id = any(v_owners);" in code
    # bot limit: keep the single oldest enabled bot, disable the rest, only for expired owners
    assert "update public.shops s set bot_enabled = false" in code
    assert "s.owner_id = any(v_owners)" in code
    assert "s.bot_enabled" in code
    assert "s.id <> (" in code
    assert "order by s2.created_at, s2.id limit 1" in code
    assert "return cardinality(v_owners);" in code
    # order: subscriptions, then mirror, then bot limit
    assert (
        code.index("update public.subscriptions")
        < code.index("update public.shops set subscription_tier")
        < code.index("update public.shops s set bot_enabled")
    )


def test_migration_0034_free_bot_limit_matches_python_tiers():
    """The SQL keeps exactly one bot (`limit 1`); if the free shop limit changes, the SQL must be updated."""
    assert TIER_LIMITS["free"]["shops"] == 1
    code = _code_of_migration()
    assert code.count(" limit 1 ") == 1


def test_migration_0034_schedules_daily_cron_once():
    code = _code_of_migration()
    # pg_cron is created only when missing (Supabase's event trigger fails on an already-enabled pg_cron)
    guard = "if not exists (select 1 from pg_catalog.pg_extension where extname = 'pg_cron') then"
    assert f"{guard} create extension pg_cron with schema pg_catalog;" in code
    assert "create extension if not exists pg_cron" not in code
    assert code.index(guard) < code.index("cron.schedule(")
    assert code.count("cron.schedule(") == 1
    assert "cron.schedule( 'expire-subscriptions', '5 0 * * *'," in code
    assert "$$select public.expire_subscriptions()$$" in code
    # the function exists before it is scheduled; everything inside the transaction
    assert code.index("create or replace function") < code.index("cron.schedule(") < code.index("commit;")


def test_migration_0034_has_no_destructive_statements():
    code = _code_of_migration()
    for forbidden in ("security definer", "delete from", "drop table", "truncate", "drop function", "unschedule"):
        assert forbidden not in code, forbidden
    # shops are only updated, never deleted or altered structurally
    assert "alter table public.shops" not in code


def test_migration_0034_documents_verification_rollback_and_deploy_order_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    assert "has_table_privilege('authenticated', 'public.subscriptions', 'insert')" in comments
    assert "has_function_privilege('authenticated', 'public.expire_subscriptions()', 'execute')" in comments
    assert "from cron.job where jobname = 'expire-subscriptions'" in comments
    assert "cron.job_run_details" in comments
    assert "--   select cron.unschedule('expire-subscriptions');" in sql
    assert "--   drop function if exists public.expire_subscriptions();" in sql
    assert "--   drop table if exists public.subscriptions;" in sql
    code = _code(sql)
    assert "drop table" not in code and "unschedule" not in code
    assert "deploy" in comments.lower()
