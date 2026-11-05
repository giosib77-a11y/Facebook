"""A-018: expired bot_conversations are actually deleted (pg_cron, migration 0030).

Static guard for the migration (no database) + the startup warning when BOT_MEMORY_HOURS
differs from the hours baked into the cron job + privacy.html §6 wording."""
import logging
import re
from pathlib import Path

from app.config import Settings
from app.main import CONVERSATION_RETENTION_HOURS, warn_if_retention_mismatch

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase" / "migrations" / "0030_bot_conversations_retention.sql"
PRIVACY = ROOT / "frontend" / "privacy.html"


def _code(sql: str) -> str:
    lines = (line for line in sql.splitlines() if not line.strip().startswith("--"))
    return re.sub(r"\s+", " ", "\n".join(lines).lower())


def test_migration_0030_schedules_hourly_purge_with_backend_hours():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert (
        "if not exists (select 1 from pg_catalog.pg_extension where extname = 'pg_cron') then "
        "create extension pg_cron with schema pg_catalog;"
    ) in code
    assert "create extension if not exists pg_cron" not in code
    assert "select cron.schedule( 'purge-expired-bot-conversations', '17 * * * *'," in code
    assert f"public.purge_expired_bot_conversations({CONVERSATION_RETENTION_HOURS})" in code
    assert code.count("begin;") == 1 and code.count("commit;") == 1


def test_migration_0030_purge_deletes_expired_but_keeps_open_handoffs():
    code = _code(MIGRATION.read_text(encoding="utf-8"))
    assert "create or replace function public.purge_expired_bot_conversations(p_hours integer)" in code
    assert "delete from public.bot_conversations where updated_at < now() - make_interval(hours => p_hours)" in code
    assert "and (not needs_attention or updated_at < now() - interval '30 days');" in code
    assert "set search_path = ''" in code
    assert "security definer" not in code
    assert (
        "revoke execute on function public.purge_expired_bot_conversations(integer) "
        "from public, anon, authenticated;"
    ) in code
    # only bot_conversations is touched
    assert code.count("delete from") == 1
    for forbidden in ("drop ", "truncate", "bot_customers", "public.orders", "create policy"):
        assert forbidden not in code, forbidden


def test_migration_0030_documents_verification_and_rollback():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "cron.job_run_details" in sql
    assert re.search(r"--\s*select cron\.unschedule\('purge-expired-bot-conversations'\);", sql)


def test_retention_mismatch_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="app"):
        warn_if_retention_mismatch(Settings(_env_file=None, bot_memory_hours=48))
    assert "BOT_MEMORY_HOURS=48" in caplog.text and "0030" in caplog.text


def test_retention_default_hours_do_not_warn(caplog):
    with caplog.at_level(logging.WARNING, logger="app"):
        warn_if_retention_mismatch(Settings(_env_file=None))
    assert caplog.text == ""


def test_privacy_section_6_states_automatic_deletion():
    html = PRIVACY.read_text(encoding="utf-8")
    sec6 = html.split("<h2>6.", 1)[1].split("<h2>7.", 1)[0]
    assert "ავტომატურად იშლება" in sec6
    assert "არაუმეტეს 30 დღისა" in sec6  # open handoff cap
