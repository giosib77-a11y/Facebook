"""F-08: admin is identified by Supabase user_id (ADMIN_USER_IDS), never by email."""
import pytest
from fastapi.testclient import TestClient

import app.api.admin
from app.config import Settings
from app.core.security import CurrentAuth, get_current_auth
from app.main import app as fastapi_app

ADMIN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
OLD_ADMIN_EMAIL = "giosib77@gmail.com"


@pytest.fixture
def check_as(monkeypatch, user_db):
    """GET /admin/check as (user_id, email) with the given ADMIN_USER_IDS value."""

    def run(user_id, email, admin_user_ids):
        settings = Settings(admin_user_ids=admin_user_ids, app_env="development")
        monkeypatch.setattr(app.api.admin, "get_settings", lambda: settings)
        fastapi_app.dependency_overrides[get_current_auth] = lambda: CurrentAuth(
            user_id=user_id, email=email, client=user_db
        )
        return TestClient(fastapi_app).get("/admin/check")

    yield run
    fastapi_app.dependency_overrides.clear()


def test_a1_listed_user_id_is_admin(check_as):
    res = check_as(ADMIN_ID, "someone@test.local", ADMIN_ID)
    assert res.status_code == 200
    assert res.json() == {"is_admin": True}


def test_a2_old_admin_email_without_listed_id_is_forbidden(check_as):
    res = check_as(OTHER_ID, OLD_ADMIN_EMAIL, ADMIN_ID)
    assert res.status_code == 403


def test_a3_empty_list_forbids_everyone(check_as):
    assert check_as(ADMIN_ID, OLD_ADMIN_EMAIL, "").status_code == 403
    assert check_as(OTHER_ID, "seller@test.local", "").status_code == 403


def test_a4_list_is_trimmed_and_case_insensitive(check_as):
    raw = f"  {ADMIN_ID.upper()} , {OTHER_ID.upper()} "
    assert check_as(ADMIN_ID, None, raw).status_code == 200
    assert check_as(OTHER_ID, None, raw).status_code == 200
