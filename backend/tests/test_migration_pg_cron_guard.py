"""Every migration creates pg_cron (and grants on the cron schema) only inside a "not installed" guard.

On Supabase, `create extension ... pg_cron` fires an event trigger even with `if not exists`; on an
already-enabled pg_cron it fails with 2BP01 ("dependent privileges exist") and the whole migration
rolls back (seen live with 0034). Static check over the SQL files only; no database."""
import re
from pathlib import Path

import pytest

MIGRATIONS = sorted((Path(__file__).resolve().parents[2] / "supabase" / "migrations").glob("*.sql"))
GUARD = "if not exists (select 1 from pg_catalog.pg_extension where extname = 'pg_cron') then"


def _code(sql: str) -> str:
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def _inside_guard(code: str, pos: int) -> bool:
    """True when `pos` lies between the pg_cron guard's `then` and its `end if;`."""
    start = code.rfind(GUARD, 0, pos)
    return start != -1 and "end if;" not in code[start:pos]


def test_migrations_exist():
    assert any(p.name.startswith("0030_") for p in MIGRATIONS)
    assert any(p.name.startswith("0034_") for p in MIGRATIONS)


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.name)
def test_pg_cron_extension_and_cron_grants_only_inside_guard(path):
    code = _code(path.read_text(encoding="utf-8"))
    risky = [m.start() for m in re.finditer(r"create extension (if not exists )?\"?pg_cron\b", code)]
    risky += [m.start() for m in re.finditer(r"\bgrant\b[^;]*\bschema cron\b", code)]
    for pos in risky:
        assert _inside_guard(code, pos), f"{path.name}: unguarded pg_cron statement: {code[pos:pos + 80]!r}"
    assert "create extension if not exists pg_cron" not in code, path.name
