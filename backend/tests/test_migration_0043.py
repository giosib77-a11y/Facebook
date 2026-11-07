"""S24-12: static guard for migration 0043 (shops_knowledge_len_chk 21 000 -> 50 000, A-042 / N-08).
Reads the file only; no database."""
import re
from pathlib import Path

from app.services.pdf_extract import MAX_CHARS

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0043_shops_knowledge_len_50k.sql"


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def _code_of_file() -> str:
    return _code(MIGRATION.read_text(encoding="utf-8"))


def test_migration_0043_replaces_the_constraint_with_the_50000_check():
    code = _code_of_file()
    assert "alter table public.shops drop constraint if exists shops_knowledge_len_chk;" in code
    assert (
        "alter table public.shops add constraint shops_knowledge_len_chk "
        "check (char_length(knowledge) <= 50000);"
    ) in code
    assert code.index("drop constraint if exists shops_knowledge_len_chk") < code.index(
        "add constraint shops_knowledge_len_chk"
    )


def test_migration_0043_limit_equals_the_pdf_extract_cap():
    # DB ceiling == code ceiling: changing one without the other must turn this red.
    limits = re.findall(r"char_length\(knowledge\) <= (\d+)", _code_of_file())
    assert limits == [str(MAX_CHARS)]


def test_migration_0043_is_one_transaction_and_touches_only_this_constraint():
    code = _code_of_file()
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.index("begin;") < code.index("drop constraint") < code.index("add constraint") < code.index("commit;")
    assert code.count("shops_knowledge_len_chk") == 2
    assert len(re.findall(r"\balter table\b", code)) == 2


def test_migration_0043_widens_only_no_old_limit_no_not_valid_no_security_changes():
    code = _code_of_file()
    for forbidden in (
        "21000",
        "not valid",
        "drop table",
        "drop column",
        "truncate",
        "delete from",
        "grant",
        "revoke",
        "policy",
        "security definer",
        "row level security",
    ):
        assert forbidden not in code, forbidden


def test_migration_0043_documents_verification_and_rollback_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    assert (
        "select pg_get_constraintdef(oid) from pg_constraint "
        "where conrelid = 'public.shops'::regclass and conname = 'shops_knowledge_len_chk';"
    ) in re.sub(r"\s+", " ", comments.replace("--", " "))
    assert "CHECK ((char_length(knowledge) <= 50000))" in comments
    assert "select max(char_length(knowledge)) from public.shops;" in comments
    assert (
        "alter table public.shops add constraint shops_knowledge_len_chk check (char_length(knowledge) <= 21000);"
    ) in comments
    # the rollback lines are comments, never executable code
    assert "21000" not in _code(sql)
