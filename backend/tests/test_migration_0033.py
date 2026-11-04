"""S20-3: static guard for migration 0033 (bot_conversations.bot_paused_until). Reads the file only; no database."""

import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0033_bot_conversations_pause.sql"


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def test_migration_0033_adds_nullable_timestamptz_column_idempotently():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "alter table public.bot_conversations add column if not exists bot_paused_until timestamptz;" in code
    assert "comment on column public.bot_conversations.bot_paused_until" in code
    # nullable: no "not null" and no default on the column
    assert "not null" not in code
    assert "default" not in code
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.index("begin;") < code.index("add column") < code.index("commit;")


def test_migration_0033_has_no_destructive_or_access_statements():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    for forbidden in ("drop table", "drop column", "delete from", "truncate", "grant", "create policy", "create function"):
        assert forbidden not in code, forbidden


def test_migration_0033_documents_verification_rollback_and_deploy_order_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    assert "information_schema.columns" in comments
    assert "timestamp with time zone, YES" in comments
    assert "pg_policies" in comments
    assert "--   alter table public.bot_conversations drop column if exists bot_paused_until;" in sql
    assert "drop" in comments.lower() and "drop" not in _code(sql)
    assert "deploy" in comments.lower()
