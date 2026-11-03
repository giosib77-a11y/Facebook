"""S19-9: static guard for migration 0032 (create_shop_limited RPC). Reads the file only; no database."""

import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0032_create_shop_limited.sql"
SIGNATURE = "public.create_shop_limited(uuid, text, text, text, text, int)"


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def test_migration_0032_function_is_locked_security_definer():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "create or replace function public.create_shop_limited(" in code
    assert "returns setof public.shops" in code
    assert "security definer" in code
    assert "set search_path = public" in code
    assert "pg_advisory_xact_lock" in code
    assert "shop_limit_reached" in code
    assert "errcode = 'p0001'" in code
    assert "p_limit is not null" in code
    assert "returning * into v_row" in code
    assert "return next v_row" in code
    assert "return query" not in code
    # the lock is taken before the count and the insert
    assert code.index("pg_advisory_xact_lock") < code.index("count(*)") < code.index("insert into public.shops")


def test_migration_0032_revokes_everyone_and_grants_only_service_role():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "revoke execute on function public.create_shop_limited" in code
    assert "from public, anon, authenticated" in code
    assert "grant execute on function public.create_shop_limited" in code
    assert "to service_role" in code
    assert re.search(r"\bgrant\b[^;]*\bto\s+(public|anon|authenticated)\b", code) is None
    assert re.findall(r"\bgrant\b[^;]*;", code) == [
        f"grant execute on function {SIGNATURE} to service_role;"
    ]
    # revoke comes before grant, both after the function definition
    assert code.index("create or replace function") < code.index("revoke execute") < code.index("grant execute")
    assert code.count("begin;") == 1 and code.count("commit;") == 1


def test_migration_0032_has_no_destructive_statements():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    for forbidden in ("drop table", "delete from", "truncate", "drop function", "alter table", "create policy"):
        assert forbidden not in code, forbidden


def test_migration_0032_documents_verification_rollback_and_deploy_order_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    assert "has_function_privilege('authenticated', 'public.create_shop_limited(uuid,text,text,text,text,int)', 'EXECUTE')" in comments
    assert "has_function_privilege('service_role', 'public.create_shop_limited(uuid,text,text,text,text,int)', 'EXECUTE')" in comments
    assert f"--   drop function if exists {SIGNATURE};" in sql
    assert "drop" in comments.lower() and "drop" not in _code(sql)
    assert "deploy" in comments.lower()
