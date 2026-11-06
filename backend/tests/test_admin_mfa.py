"""Stage 23 (A-043 / N-06): ადმინის MFA — `get_current_admin` მოითხოვს `aal2`-ს (`ADMIN_REQUIRE_MFA`).

რიგი: ADMIN_USER_IDS -> MFA (ლოკალური claim) -> Auth server-ით დადასტურება. ყველაფერი offline.
"""
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.admin as admin_module
from app.config import Settings
from app.core.security import CurrentAuth, get_current_auth
from app.main import app as fastapi_app

ADMIN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
MFA_DETAIL = "ადმინ პანელისთვის საჭიროა ორფაქტორიანი შესვლა (MFA)"
NOT_ADMIN_DETAIL = "წვდომა მხოლოდ ადმინისთვის"
ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


class _CountingAuth:
    """`client.auth` — `get_user(token)` ითვლის გამოძახებებს და ადმინ user-ს აბრუნებს."""

    def __init__(self, user_id=ADMIN_ID):
        self.calls = 0
        self.user_id = user_id

    def get_user(self, token):
        self.calls += 1
        return SimpleNamespace(user=SimpleNamespace(id=self.user_id, email=None))


@pytest.fixture
def mfa_env(monkeypatch, user_db):
    """`run(method, path, ...)` — მოთხოვნა მოცემული user_id / claims / verified_by-ით და settings-ით."""
    user_db.auth = _CountingAuth()

    def configure(*, app_env="development", admin_require_mfa=True, admin_user_ids=ADMIN_ID):
        settings = Settings(
            admin_user_ids=admin_user_ids, app_env=app_env, admin_require_mfa=admin_require_mfa,
            _env_file=None,
        )
        monkeypatch.setattr(admin_module, "get_settings", lambda: settings)

    def run(claims, *, user_id=ADMIN_ID, verified_by="network", method="GET", path="/admin/check", json=None):
        fastapi_app.dependency_overrides[get_current_auth] = lambda: CurrentAuth(
            user_id=user_id, email=None, client=user_db, claims=claims,
            token="tok-not-real", verified_by=verified_by,
        )
        return TestClient(fastapi_app).request(method, path, json=json)

    configure()
    run.configure = configure
    run.db = user_db
    yield run
    fastapi_app.dependency_overrides.clear()


# --- (1)-(5) ძირითადი ქცევა ------------------------------------------------------------------

def test_aal1_admin_gets_mfa_403_when_required(mfa_env):
    res = mfa_env({"aal": "aal1"})
    assert res.status_code == 403
    assert res.json() == {"detail": MFA_DETAIL}


def test_aal2_admin_passes(mfa_env):
    res = mfa_env({"aal": "aal2"})
    assert res.status_code == 200
    assert res.json() == {"is_admin": True}


def test_missing_aal_claim_is_mfa_403(mfa_env):
    assert mfa_env({}).json() == {"detail": MFA_DETAIL}
    assert mfa_env({"sub": ADMIN_ID}).status_code == 403
    assert mfa_env({"aal": None}).status_code == 403


def test_non_admin_with_aal2_gets_admin_403_not_mfa_text(mfa_env):
    res = mfa_env({"aal": "aal2"}, user_id=OTHER_ID)
    assert res.status_code == 403
    assert res.json() == {"detail": NOT_ADMIN_DETAIL}
    # არა-ადმინი aal1-ითაც "არა ადმინია" - MFA-ს ტექსტი ადმინობას არ ამხელს
    assert mfa_env({"aal": "aal1"}, user_id=OTHER_ID).json() == {"detail": NOT_ADMIN_DETAIL}


def test_mfa_off_lets_aal1_through(mfa_env):
    mfa_env.configure(admin_require_mfa=False)
    res = mfa_env({"aal": "aal1"})
    assert res.status_code == 200
    assert res.json() == {"is_admin": True}


# --- (6) MFA შემოწმება Auth server-მდეა --------------------------------------------------------

def test_mfa_checked_before_auth_server(mfa_env):
    res = mfa_env({"aal": "aal1"}, verified_by="local")
    assert res.status_code == 403
    assert res.json() == {"detail": MFA_DETAIL}
    assert mfa_env.db.auth.calls == 0

    res = mfa_env({"aal": "aal2"}, verified_by="local")
    assert res.status_code == 200
    assert mfa_env.db.auth.calls == 1


def test_aal2_local_token_still_rejected_when_auth_server_disagrees(mfa_env):
    mfa_env.db.auth.user_id = OTHER_ID  # Auth server სხვა user-ს აბრუნებს
    res = mfa_env({"aal": "aal2"}, verified_by="local")
    assert res.status_code == 401
    assert mfa_env.db.auth.calls == 1


# --- (7) ყველა /admin route დაცულია -----------------------------------------------------------

def _depends_on(dependant, func) -> bool:
    return any(d.call is func or _depends_on(d, func) for d in dependant.dependencies)


def test_every_admin_route_depends_on_get_current_admin():
    # FastAPI-ს ახალ ვერსიაში app.routes include_router-ის route-ებს ზარმაცად ინახავს (_IncludedRouter) -
    # ამიტომ route-ები router-იდან იკითხება, ხოლო app-ში გამოჩენილი /admin path-ები openapi-ით მოწმდება
    admin_routes = admin_module.router.routes
    assert len(admin_routes) >= 10
    router_paths = {r.path for r in admin_routes}
    assert all(p.startswith("/admin") for p in router_paths)
    app_admin_paths = {p for p in fastapi_app.openapi()["paths"] if p.startswith("/admin")}
    assert app_admin_paths and app_admin_paths <= router_paths  # სხვა მოდულში /admin route არ ჩნდება დაუცველად
    unguarded = [r.path for r in admin_routes if not _depends_on(r.dependant, admin_module.get_current_admin)]
    assert unguarded == []


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/admin/overview", None),
        ("PATCH", "/admin/shops/x", {"bot_enabled": False}),
        ("POST", "/admin/recovery", {"email": "seller@test.local"}),
    ],
)
def test_mfa_applies_to_admin_routes_without_touching_db(mfa_env, monkeypatch, method, path, body):
    def boom():
        raise AssertionError("get_service_client must not be called before the MFA check")

    monkeypatch.setattr(admin_module, "get_service_client", boom)
    res = mfa_env({"aal": "aal1"}, method=method, path=path, json=body)
    assert res.status_code == 403
    assert res.json() == {"detail": MFA_DETAIL}


# --- (8) settings -----------------------------------------------------------------------------

def test_settings_default_follows_environment():
    assert Settings(app_env="production", _env_file=None).admin_mfa_required is True
    assert Settings(app_env="development", _env_file=None).admin_mfa_required is False


def test_settings_explicit_value_wins():
    assert Settings(app_env="production", admin_require_mfa=False, _env_file=None).admin_mfa_required is False
    assert Settings(app_env="development", admin_require_mfa=True, _env_file=None).admin_mfa_required is True


def test_blank_env_value_is_none(monkeypatch):
    monkeypatch.setenv("ADMIN_REQUIRE_MFA", "")
    s = Settings(app_env="production", _env_file=None)
    assert s.admin_require_mfa is None
    assert s.admin_mfa_required is True
    monkeypatch.setenv("ADMIN_REQUIRE_MFA", "false")
    assert Settings(app_env="production", _env_file=None).admin_mfa_required is False


def test_env_example_documents_the_flag_and_tests_do_not_set_it():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert any(line.strip().lstrip("#").strip().startswith("ADMIN_REQUIRE_MFA=") for line in text.splitlines())
    import os

    assert "ADMIN_REQUIRE_MFA" not in os.environ


def test_settings_object_without_mfa_attribute_follows_environment_default(mfa_env, monkeypatch):
    # ველის გარეშე (მაგ. ტესტის fake settings) production-ში MFA არ ითიშება (fail closed)
    for is_prod, expected in ((True, 403), (False, 200)):
        fake = SimpleNamespace(admin_user_id_set={ADMIN_ID}, is_production=is_prod)
        monkeypatch.setattr(admin_module, "get_settings", lambda fake=fake: fake)
        assert mfa_env({"aal": "aal1"}).status_code == expected


# --- (9) production-ში გამორთული MFA - ერთი WARNING ---------------------------------------------

def _mfa_warnings(caplog):
    return [r for r in caplog.records if "ADMIN_REQUIRE_MFA is off in production" in r.getMessage()]


def test_production_with_mfa_off_warns_once_per_process(mfa_env, monkeypatch, caplog):
    monkeypatch.setattr(admin_module, "_warned_no_mfa", False)
    mfa_env.configure(app_env="production", admin_require_mfa=False)
    with caplog.at_level(logging.WARNING, logger="app"):
        assert mfa_env({"aal": "aal1"}).status_code == 200
        assert mfa_env({"aal": "aal1"}).status_code == 200
    assert len(_mfa_warnings(caplog)) == 1
    assert "tok-not-real" not in caplog.text
    assert ADMIN_ID not in caplog.text


def test_no_mfa_warning_when_enforced_or_in_development(mfa_env, monkeypatch, caplog):
    monkeypatch.setattr(admin_module, "_warned_no_mfa", False)
    with caplog.at_level(logging.WARNING, logger="app"):
        mfa_env.configure(app_env="production", admin_require_mfa=True)
        assert mfa_env({"aal": "aal2"}).status_code == 200
        mfa_env.configure(app_env="development", admin_require_mfa=False)
        assert mfa_env({"aal": "aal1"}).status_code == 200
    assert _mfa_warnings(caplog) == []
