"""S18-1: static guard for migration 0028 (products.image_description). Reads the file only; no database."""

import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0028_products_image_description.sql"


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def test_migration_0028_adds_only_the_nullable_image_description_column():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "alter table public.products add column if not exists image_description text;" in code
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.index("begin;") < code.index("add column") < code.index("commit;")
    assert code.count("add column") == 1
    assert "not null" not in code and "default" not in code and "check" not in code
    assert "comment on column public.products.image_description is" in code


def test_migration_0028_has_no_grants_policies_or_destructive_statements():
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


def test_migration_0028_documents_verification_and_rollback_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    assert "has_column_privilege('authenticated','public.products','image_description','UPDATE')" in comments
    assert "has_table_privilege('authenticated','public.products','UPDATE')" in comments
    assert "has_table_privilege('authenticated','public.products','INSERT')" in comments
    assert "has_column_privilege('authenticated','public.products','image_description','SELECT')" in comments
    assert "has_column_privilege('service_role','public.products','image_description','UPDATE')" in comments
    assert "information_schema.columns" in comments
    # rollback exists only as a comment
    assert re.search(r"--\s*alter table public\.products drop column if exists image_description;", sql)
    assert "drop" in comments.lower() and "drop" not in _code(sql)
    assert "deploy" in comments.lower()
