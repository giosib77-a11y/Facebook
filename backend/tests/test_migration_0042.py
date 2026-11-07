"""S24-11: static guard for migration 0042 (drop the unused llm_tokens_used RPC, A-042 / N-08).
Reads the file only; no database."""
import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0042_drop_llm_tokens_used.sql"


def _code(sql: str) -> str:
    """SQL without `--` comment lines, lower-cased, whitespace collapsed."""
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))


def _code_of_file() -> str:
    return _code(MIGRATION.read_text(encoding="utf-8"))


def test_migration_0042_is_exactly_one_drop_function_if_exists_statement():
    code = _code_of_file()
    statements = [s.strip() for s in code.split(";") if s.strip()]
    assert statements == [
        "begin",
        "drop function if exists public.llm_tokens_used(uuid, timestamptz)",
        "commit",
    ]


def test_migration_0042_is_one_transaction():
    code = _code_of_file()
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.index("begin;") < code.index("drop function") < code.index("commit;")


def test_migration_0042_creates_and_changes_nothing_else():
    code = _code_of_file()
    for forbidden in (
        "create",
        "grant",
        "revoke",
        "drop table",
        "drop index",
        "alter",
        "cascade",
        "llm_usage_by_model",
        "llm_usage_created_idx",
        "policy",
    ):
        assert forbidden not in code, forbidden


def test_migration_0042_documents_verification_and_rollback_in_comments_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    comments = _comments(sql)
    assert "select to_regprocedure('public.llm_tokens_used(uuid,timestamptz)');" in comments
    assert "select to_regprocedure('public.llm_usage_by_model(uuid,uuid,timestamptz)') is not null;" in comments
    assert "0035" in comments and "idempotent" in comments
    assert "llm_usage_created_idx" in comments  # the index stays
    assert "Stage 24" in comments and "deploy" in comments
    # the verification queries are comments, never executable code
    assert "to_regprocedure" not in _code(sql)
