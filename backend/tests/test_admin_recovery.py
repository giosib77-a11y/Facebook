"""A-043 (N-06): POST /admin/recovery - the password-recovery link goes to the seller's mailbox, never
back to the admin (a stolen admin account must not be able to take over any seller account).
Offline: FakeSupabase + fake `auth.admin.generate_link` + fake `notify.send_email`."""
import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.admin
from app.api.admin import get_current_admin
from app.config import Settings
from app.core.security import CurrentAuth
from app.main import app as fastapi_app
from app.services import admin_audit
from tests.conftest import FakeSupabase

ADMIN = "admin-uuid"
SELLER_ID = "11111111-2222-3333-4444-555555555555"
SELLER_EMAIL = "seller@test.local"
LINK = "https://proj.supabase.co/auth/v1/verify?type=recovery&token=SECRET-TOKEN-123&redirect_to=x"
BASE = "https://chatassist.test"
REDIRECT = f"{BASE}/panel/reset.html"
NO_SMTP = "ელფოსტა არ არის კონფიგურირებული (SMTP) — აღდგენის ბმული ვერ გაიგზავნება"
GEN_FAILED = "ბმულის გენერაცია ვერ მოხერხდა"
NOT_SENT = "ბმული შეიქმნა, მაგრამ ელფოსტა ვერ გაიგზავნა — სცადე ხელახლა"
SUBJECT = "ChatAssist — პაროლის აღდგენა"
TABLE = "admin_audit_log"


def _settings(*, smtp=True, base=BASE):
    kwargs = {"public_base_url": base, "_env_file": None}
    if smtp:
        kwargs.update(
            smtp_host="smtp.test", smtp_user="u", smtp_password="p", notify_email_from="noreply@test.local"
        )
    return Settings(**kwargs)


class Recorder:
    """Fake generate_link + send_email; counts calls and keeps arguments."""

    def __init__(self):
        self.params: list = []
        self.sent: list = []
        self.link = LINK
        self.user_id = SELLER_ID
        self.generate_error: Exception | None = None
        self.send_result = True

    def generate_link(self, params):
        self.params.append(params)
        if self.generate_error is not None:
            raise self.generate_error
        return SimpleNamespace(
            properties=SimpleNamespace(action_link=self.link),
            user=SimpleNamespace(id=self.user_id) if self.user_id else None,
        )

    def send_email(self, to, subject, text):
        self.sent.append((to, subject, text))
        return self.send_result


@pytest.fixture(autouse=True)
def _fresh_audit_flag():
    admin_audit._reset_for_tests()
    yield
    admin_audit._reset_for_tests()


@pytest.fixture
def env(monkeypatch):
    db = FakeSupabase()
    rec = Recorder()
    db.auth = SimpleNamespace(admin=SimpleNamespace(generate_link=rec.generate_link))
    monkeypatch.setattr(app.api.admin, "get_service_client", lambda: db)
    monkeypatch.setattr(app.api.admin, "get_settings", lambda: _settings())
    monkeypatch.setattr(app.api.admin.notify, "send_email", rec.send_email)
    fastapi_app.dependency_overrides[get_current_admin] = lambda: CurrentAuth(
        user_id=ADMIN, email=None, client=db
    )
    rec.db = db
    rec.settings = lambda **kw: monkeypatch.setattr(app.api.admin, "get_settings", lambda: _settings(**kw))
    try:
        yield rec
    finally:
        fastapi_app.dependency_overrides.clear()


def _post(email=SELLER_EMAIL):
    return TestClient(fastapi_app).post("/admin/recovery", json={"email": email})


def _audit_rows(rec):
    return [c.payload for c in rec.db.calls_for(TABLE, "insert")]


# (1) the link goes to the seller's mailbox and is hidden from the admin

def test_recovery_emails_link_and_hides_it(env):
    res = _post()
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert "action_link" not in res.text
    assert LINK not in res.text and "SECRET-TOKEN-123" not in res.text
    assert len(env.sent) == 1
    to, subject, body = env.sent[0]
    assert to == SELLER_EMAIL
    assert subject == SUBJECT
    assert LINK in body.splitlines()  # the link sits on its own line
    assert "მხარდაჭერის მოთხოვნით" in body
    assert "ბმული ერთჯერადია და მალე იწურება; თუ ეს თქვენ არ მოგითხოვიათ — უგულებელყავით წერილი" in body


# (2) redirect_to

def test_recovery_params_have_redirect_to_panel_reset_page(env):
    assert _post().status_code == 200
    assert env.params == [
        {"type": "recovery", "email": SELLER_EMAIL, "options": {"redirect_to": REDIRECT}}
    ]


def test_recovery_redirect_to_strips_trailing_slash(env):
    env.settings(base=BASE + "/")
    assert _post().status_code == 200
    assert env.params[0]["options"] == {"redirect_to": REDIRECT}


def test_recovery_empty_public_base_url_sends_no_options(env):
    env.settings(base="")
    assert _post().status_code == 200
    assert env.params == [{"type": "recovery", "email": SELLER_EMAIL}]
    assert len(env.sent) == 1


# (3) no SMTP -> 503 before any link exists

def test_recovery_without_smtp_is_503(env):
    env.settings(smtp=False)
    res = _post()
    assert res.status_code == 503
    assert res.json() == {"detail": NO_SMTP}
    assert env.params == []  # no link generated
    assert env.sent == []
    assert _audit_rows(env) == []


def test_recovery_with_partially_configured_smtp_is_503(env, monkeypatch):
    partial = Settings(smtp_host="smtp.test", smtp_user="u", _env_file=None)  # no password / from
    monkeypatch.setattr(app.api.admin, "get_settings", lambda: partial)
    res = _post()
    assert res.status_code == 503 and res.json() == {"detail": NO_SMTP}
    assert env.params == [] and env.sent == []


# (4) generate_link failure never leaks exception text

def test_generate_error_hides_exception_text(env, caplog):
    env.generate_error = Exception("db password=xyz")
    with caplog.at_level(logging.DEBUG):
        res = _post()
    assert res.status_code == 400
    assert res.json() == {"detail": GEN_FAILED}
    assert "xyz" not in res.text
    assert "xyz" not in caplog.text
    assert "recovery link generation failed (Exception)" in caplog.text
    assert SELLER_EMAIL not in caplog.text
    assert env.sent == []
    assert _audit_rows(env) == []


@pytest.mark.parametrize("bad", ["", None])
def test_empty_action_link_is_400(env, bad):
    env.link = bad
    res = _post()
    assert res.status_code == 400 and res.json() == {"detail": GEN_FAILED}
    assert env.sent == []
    assert _audit_rows(env) == []


def test_generate_link_without_properties_is_400(env, monkeypatch):
    env.db.auth.admin.generate_link = lambda params: SimpleNamespace(properties=None, user=None)
    res = _post()
    assert res.status_code == 400 and res.json() == {"detail": GEN_FAILED}
    assert env.sent == []


# (5) send failure -> 502, audited with email_sent False

def test_send_failure_is_502_and_audited(env):
    env.send_result = False
    res = _post()
    assert res.status_code == 502
    assert res.json() == {"detail": NOT_SENT}
    assert LINK not in res.text
    assert len(env.sent) == 1
    rows = _audit_rows(env)
    assert len(rows) == 1
    assert rows[0]["details"] == {"email_sent": False}


# (6) audit row

def test_audit_row_for_successful_recovery(env):
    assert _post().status_code == 200
    rows = _audit_rows(env)
    assert len(rows) == 1
    row = rows[0]
    assert row["action"] == "seller.recovery"
    assert row["admin_id"] == ADMIN
    assert row["target"] == SELLER_ID
    assert row["details"] == {"email_sent": True}
    assert SELLER_EMAIL not in str(row) and LINK not in str(row)


def test_audit_target_is_none_when_user_is_unknown(env):
    env.user_id = None
    assert _post().status_code == 200
    rows = _audit_rows(env)
    assert len(rows) == 1 and rows[0]["target"] is None


def test_audit_write_failure_does_not_block_recovery(env):
    env.db.errors[(TABLE, "insert")] = RuntimeError("audit down")
    res = _post()
    assert res.status_code == 200 and res.json() == {"ok": True}
    assert len(env.sent) == 1


# (7) neither the link nor the address is ever logged

@pytest.mark.parametrize("send_result", [True, False])
def test_link_and_email_are_never_logged(env, caplog, send_result):
    env.send_result = send_result
    with caplog.at_level(logging.DEBUG):
        _post()
    assert LINK not in caplog.text
    assert "SECRET-TOKEN-123" not in caplog.text
    assert SELLER_EMAIL not in caplog.text


# (8) input validation

def test_email_is_stripped(env):
    assert _post("  a@b.ge  ").status_code == 200
    assert env.params[0]["email"] == "a@b.ge"
    assert env.sent[0][0] == "a@b.ge"


@pytest.mark.parametrize("bad", ["", "   ", "a", "x" * 321])
def test_invalid_email_is_422(env, bad):
    res = _post(bad)
    assert res.status_code == 422
    assert env.params == [] and env.sent == []


def test_missing_email_is_422(env):
    res = TestClient(fastapi_app).post("/admin/recovery", json={})
    assert res.status_code == 422
    assert env.params == [] and env.sent == []


def test_max_length_email_is_accepted(env):
    assert _post("x" * 320).status_code == 200
