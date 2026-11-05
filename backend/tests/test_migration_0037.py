"""S21-2: static guard for migration 0037 (webhook_inbox table + claim/purge functions + pg_cron job).
Reads the file only; no database."""
import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0037_webhook_inbox.sql"


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def _code_of_file() -> str:
    return _code(MIGRATION.read_text(encoding="utf-8"))


def test_migration_0037_table_has_the_dedup_key_and_the_checks():
    code = _code_of_file()
    assert "create table if not exists public.webhook_inbox" in code
    assert "constraint webhook_inbox_page_mid_key unique (page_id, mid)" in code
    assert "page_id text not null check (page_id ~ '^[0-9]{1,32}$')" in code
    assert "mid text not null check (char_length(mid) between 1 and 200)" in code
    assert "object text not null check (object in ('page', 'instagram'))" in code
    assert "check (status in ('pending', 'processing', 'done', 'failed'))" in code
    assert "last_error text check (char_length(last_error) <= 200)" in code
    assert "event jsonb," in code  # nullable: set to null once processed
    assert "create index if not exists webhook_inbox_status_next_idx on public.webhook_inbox (status, next_attempt_at);" in code
    assert "create index if not exists webhook_inbox_created_idx on public.webhook_inbox (created_at);" in code


def test_migration_0037_is_backend_only_rls_on_no_policy_no_client_grants():
    code = _code_of_file()
    assert "alter table public.webhook_inbox enable row level security;" in code
    assert "revoke all on table public.webhook_inbox from public, anon, authenticated;" in code
    assert "grant select, insert, update, delete on table public.webhook_inbox to service_role;" in code
    assert "grant usage, select on sequence public.webhook_inbox_id_seq to service_role;" in code
    for forbidden in ("create policy", "security definer", "to anon", "to authenticated", "to public"):
        assert forbidden not in code, forbidden
    assert re.search(r"\bgrant\b[^;]*\bto\s+(public|anon|authenticated)\b", code) is None


def test_migration_0037_claim_function_skips_locked_rows_and_is_invoker_with_empty_search_path():
    code = _code_of_file()
    assert (
        "create or replace function public.claim_webhook_events"
        "(p_limit integer, p_stale_seconds integer, p_max_attempts integer) "
        "returns setof public.webhook_inbox language sql volatile set search_path = ''"
    ) in code
    assert "for update skip locked" in code
    assert "i.attempts < p_max_attempts" in code
    assert "i.status = 'pending' and i.next_attempt_at <= now()" in code
    assert "i.status = 'processing' and i.claimed_at < now() - make_interval(secs => p_stale_seconds)" in code
    assert "limit greatest(1, least(p_limit, 50))" in code
    assert "set status = 'processing', claimed_at = now(), attempts = w.attempts + 1" in code
    assert "returning w.*" in code


def test_migration_0037_purge_function_rejects_negative_hours_and_deletes_only_inside_itself():
    code = _code_of_file()
    assert "create or replace function public.purge_webhook_inbox(p_hours integer) returns integer language plpgsql" in code
    start = code.index("create or replace function public.purge_webhook_inbox")
    end = code.index("revoke execute on function public.purge_webhook_inbox")
    body = code[start:end]
    assert "if p_hours < 0 then raise exception" in body
    assert "delete from public.webhook_inbox where created_at < now() - make_interval(hours => p_hours)" in body
    # the only DELETE statement lives in the purge function
    assert code.count("delete from public.webhook_inbox") == 1
    assert len(re.findall(r"\bdelete from\b", code)) == 1


def test_migration_0037_revokes_function_execute_from_clients_and_grants_claim_to_service_role_only():
    code = _code_of_file()
    assert (
        "revoke execute on function public.claim_webhook_events(integer, integer, integer) "
        "from public, anon, authenticated;"
    ) in code
    assert "revoke execute on function public.purge_webhook_inbox(integer) from public, anon, authenticated;" in code
    function_grants = [g for g in re.findall(r"\bgrant\b[^;]*;", code) if " function " in g]
    assert function_grants == [
        "grant execute on function public.claim_webhook_events(integer, integer, integer) to service_role;"
    ]
    assert code.index("create or replace function public.claim_webhook_events") < code.index(
        "revoke execute on function public.claim_webhook_events"
    ) < code.index("grant execute on function public.claim_webhook_events")


def test_migration_0037_schedules_the_hourly_purge_behind_the_pg_cron_guard():
    code = _code_of_file()
    assert "cron.schedule(" in code
    assert "'purge-webhook-inbox'" in code and "'23 * * * *'" in code
    assert "$$select public.purge_webhook_inbox(24)$$" in code
    guard = "if not exists (select 1 from pg_catalog.pg_extension where extname = 'pg_cron') then"
    assert guard in code
    assert "create extension if not exists pg_cron" not in code
    ext = code.index("create extension pg_cron")
    assert code.rindex(guard, 0, ext) < ext < code.index("end if;", ext) < code.index("cron.schedule(")


def test_migration_0037_is_one_transaction_and_non_destructive():
    code = _code_of_file()
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.index("begin;") < code.index("create table") < code.index("cron.schedule(") < code.index("commit;")
    for forbidden in ("drop table", "drop function", "truncate", "alter table public.webhook_inbox drop"):
        assert forbidden not in code, forbidden


def test_migration_0037_documents_verification_rollback_and_deploy_order_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    assert "has_function_privilege('authenticated', 'public.claim_webhook_events(integer,integer,integer)', 'execute')" in comments
    assert "select * from public.claim_webhook_events(1, 180, 3);" in comments
    assert "from cron.job where jobname = 'purge-webhook-inbox'" in comments
    assert "--   select cron.unschedule('purge-webhook-inbox');" in sql
    assert "--   drop function if exists public.purge_webhook_inbox(integer);" in sql
    assert "--   drop function if exists public.claim_webhook_events(integer, integer, integer);" in sql
    assert "--   drop table if exists public.webhook_inbox;" in sql
    assert "drop" not in _code(sql)
    assert "deploy" in comments.lower() and "event = null" in comments
