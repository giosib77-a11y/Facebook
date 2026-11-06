"""S23-2: static guard for migration 0041 (admin_audit_log: append-only trace of admin changes, A-043).
Reads the file only; no database."""
import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0041_admin_audit_log.sql"


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def _code_of_file() -> str:
    return _code(MIGRATION.read_text(encoding="utf-8"))


def test_migration_0041_table_has_not_null_columns_and_the_checks():
    code = _code_of_file()
    assert "create table if not exists public.admin_audit_log" in code
    assert "id bigint generated always as identity primary key" in code
    assert "admin_id uuid not null" in code
    assert (
        "action text not null check (action ~ '^[a-z_]+\\.[a-z_]+$' and char_length(action) <= 64)"
    ) in code
    assert "target text check (char_length(target) <= 64)" in code
    assert "details jsonb not null default '{}'::jsonb" in code
    assert "check (jsonb_typeof(details) = 'object' and pg_column_size(details) <= 2048)" in code
    assert "created_at timestamptz not null default now()" in code
    assert (
        "create index if not exists admin_audit_log_created_at_idx "
        "on public.admin_audit_log (created_at desc);"
    ) in code


def test_migration_0041_has_no_foreign_key_so_the_trace_outlives_the_admin_account():
    code = _code_of_file()
    assert "references" not in code
    assert "references auth.users" not in code
    assert "foreign key" not in code


def test_migration_0041_is_backend_only_rls_on_no_policy_nothing_for_clients():
    code = _code_of_file()
    assert "alter table public.admin_audit_log enable row level security;" in code
    assert "revoke all on table public.admin_audit_log from public, anon, authenticated, service_role;" in code
    assert "revoke all on sequence public.admin_audit_log_id_seq from public, anon, authenticated;" in code
    for forbidden in ("create policy", "security definer", "to anon", "to authenticated", "to public"):
        assert forbidden not in code, forbidden
    # no grant at all may target public/anon/authenticated (a `revoke ... from anon` is fine)
    assert re.search(r"\bgrant\b[^;]*\bto\s+(public|anon|authenticated)\b", code) is None


def test_migration_0041_service_role_is_append_only_select_and_insert():
    code = _code_of_file()
    assert "grant select, insert on table public.admin_audit_log to service_role;" in code
    assert "grant usage, select on sequence public.admin_audit_log_id_seq to service_role;" in code
    for forbidden in ("grant update", "grant delete", "grant all", "grant truncate", "grant references", "grant trigger"):
        assert forbidden not in code, forbidden
    table_grants = [g for g in re.findall(r"\bgrant\b[^;]*;", code) if " on table " in g]
    assert table_grants == ["grant select, insert on table public.admin_audit_log to service_role;"]
    # the revoke comes before the grant (otherwise the revoke would wipe it)
    assert code.index("revoke all on table public.admin_audit_log") < code.index("grant select, insert on table")
    assert code.index("revoke all on sequence public.admin_audit_log_id_seq") < code.index(
        "grant usage, select on sequence"
    )


def test_migration_0041_is_one_transaction_non_destructive_and_has_no_pg_cron():
    code = _code_of_file()
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.index("begin;") < code.index("create table") < code.index("enable row level security") < code.index("commit;")
    for forbidden in ("drop table", "drop index", "truncate", "delete from", "cron.schedule", "pg_cron", "references auth.users"):
        assert forbidden not in code, forbidden


def test_migration_0041_documents_verification_and_rollback_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    assert "select relrowsecurity from pg_class where oid = 'public.admin_audit_log'::regclass;" in comments
    assert (
        "select count(*) from pg_policies where schemaname = 'public' and tablename = 'admin_audit_log';"
    ) in comments
    for privilege in ("select", "insert", "update", "delete"):
        assert f"has_table_privilege('service_role', 'public.admin_audit_log', '{privilege}')" in comments
    assert "has_table_privilege('anon', 'public.admin_audit_log', 'select')" in comments
    assert "has_table_privilege('authenticated', 'public.admin_audit_log', 'insert')" in comments
    assert "--   drop table if exists public.admin_audit_log;" in sql
    assert "drop" not in _code(sql)
    assert "deploy" in comments.lower() and "WARNING" in comments
