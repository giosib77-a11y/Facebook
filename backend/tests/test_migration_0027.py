"""S17-1: static guard for migration 0027 (shops.knowledge_faq). Reads the file only; no database."""

import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0027_shops_knowledge_faq.sql"


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def test_migration_0027_adds_only_the_nullable_knowledge_faq_column():
    sql = MIGRATION.read_text(encoding="utf-8")
    code = _code(sql)
    assert "alter table public.shops add column if not exists knowledge_faq text;" in code
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.index("begin;") < code.index("add column") < code.index("commit;")
    assert "not null" not in code and "default" not in code
    assert "comment on column public.shops.knowledge_faq is" in code


def test_migration_0027_has_no_grants_policies_or_destructive_statements():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    for forbidden in (
        "grant",
        "revoke",
        "create policy",
        "alter policy",
        "security definer",
        "create table",
        "create index",
        "create function",
        "drop",
        "delete from",
        "update public.",
        "truncate",
    ):
        assert forbidden not in code, forbidden


def test_migration_0027_documents_verification_and_rollback_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    assert "has_column_privilege('authenticated','public.shops','knowledge_faq','UPDATE')" in comments
    assert "has_table_privilege('authenticated','public.shops','UPDATE')" in comments
    assert "has_column_privilege('authenticated','public.shops','knowledge_faq','SELECT')" in comments
    assert "has_column_privilege('service_role','public.shops','knowledge_faq','UPDATE')" in comments
    assert "information_schema.columns" in comments
    # rollback exists only as a comment
    assert re.search(r"--\s*alter table public\.shops drop column if exists knowledge_faq;", sql)
    assert "drop" in comments.lower() and "drop" not in _code(sql)
    assert "deploy" in comments.lower()
