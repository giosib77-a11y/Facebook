"""S20-11: static guard for migration 0036 (shops.bot_status / bot_status_at). Reads the file only; no database."""

import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0036_shops_bot_status.sql"

STATUSES = ("ok", "token_error", "token_expired", "send_failed", "budget_exhausted")


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def test_migration_0036_adds_nullable_bot_status_with_the_five_values_idempotently():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "add column if not exists bot_status text" in code
    m = re.search(r"add column if not exists bot_status text check \(bot_status in \(([^)]*)\)\)", code)
    assert m, "check constraint on bot_status missing"
    assert tuple(v.strip().strip("'") for v in m.group(1).split(",")) == STATUSES
    assert "add column if not exists bot_status_at timestamptz;" in code
    assert "comment on column public.shops.bot_status " in code
    assert "comment on column public.shops.bot_status_at " in code
    # nullable, no default
    assert "not null" not in code
    assert "default" not in code
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.index("begin;") < code.index("add column") < code.index("commit;")


def test_migration_0036_has_no_destructive_or_access_statements():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    for forbidden in ("drop table", "drop column", "delete from", "truncate", "grant", "revoke", "create policy"):
        assert forbidden not in code, forbidden


def test_migration_0036_documents_verification_and_rollback_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    assert "information_schema.columns" in comments
    assert "text, YES" in comments and "timestamp with time zone, YES" in comments
    assert "has_column_privilege('authenticated', 'public.shops', 'bot_status', 'UPDATE')" in comments
    assert "has_column_privilege('authenticated', 'public.shops', 'bot_status', 'SELECT')" in comments
    assert "--   alter table public.shops drop column if exists bot_status;" in sql
    assert "--   alter table public.shops drop column if exists bot_status_at;" in sql
    assert "drop" in comments.lower() and "drop" not in _code(sql)
    assert "deploy" in comments.lower()
