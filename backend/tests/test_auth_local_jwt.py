"""Stage 22 (A-046 / N-10): `get_current_auth` — ლოკალური JWT შემოწმება, `CurrentAuth.claims`,
ადმინი ყოველთვის Auth server-ითაც.

`dependency_overrides` არ გამოიყენება: რეალური dependency გადის FastAPI-ში. Supabase კლიენტი —
`security.create_client`-ის fake (`get_user` მთვლელი, `postgrest.auth` ჩანაწერი), JWKS — `PyJWKClient.fetch_data`-ის
fake (`tests/test_jwt_verify.py`-ის helper-ები). ქსელი არ გამოიყენება.
"""
import base64
import json
import logging
import time
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import admin as admin_module
from app.core import jwt_verify, security
from app.main import app as fastapi_app
from tests.conftest import FakeSupabase
from tests.test_jwt_verify import (
    SUPABASE_URL,
    USER_EMAIL,
    USER_SUB,
    install_jwks,
    jwks,
    make_claims,
    make_es256_keypair,
    sign,
)

ADMIN_SUB = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
INVALID_DETAIL = "token არასწორია ან ვადაგასულია"
NO_USER_DETAIL = "token არ შეესაბამება მომხმარებელს"
HS_SECRET = "legacy-hs256-secret-0123456789-0123456789"


class FakeAuthApi:
    """`client.auth` — `get_user(token)` ითვლის გამოძახებებს; `error` ისვრის, `user` აბრუნებს."""

    def __init__(self):
        self.calls: list[str] = []
        self.user = SimpleNamespace(id=USER_SUB, email=USER_EMAIL)
        self.error: Exception | None = None
        self.no_user = False

    def get_user(self, token):
        self.calls.append(token)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(user=None if self.no_user else self.user)


class FakePostgrest:
    def __init__(self):
        self.tokens: list[str] = []

    def auth(self, token):
        self.tokens.append(token)


class FakeAuthClient(FakeSupabase):
    def __init__(self):
        super().__init__()
        self.auth = FakeAuthApi()
        self.postgrest = FakePostgrest()


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    """settings (supabase_url + ადმინის id) სამივე მოდულისთვის და სუფთა jwt_verify state."""
    jwt_verify._reset_for_tests()
    settings = SimpleNamespace(
        supabase_url=SUPABASE_URL, supabase_publishable_key="sb_publishable_test",
        jwt_local_verify=True, admin_user_id_set={ADMIN_SUB}, is_production=False,
    )
    for module in (jwt_verify, security, admin_module):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    yield settings
    jwt_verify._reset_for_tests()


@pytest.fixture
def fake(monkeypatch):
    """ერთი fake Supabase კლიენტი; `fake.created` — რამდენჯერ გამოიძახეს `create_client`."""
    client = FakeAuthClient()
    client.created = 0

    def create(*args, **kwargs):
        client.created += 1
        return client

    monkeypatch.setattr(security, "create_client", create)
    return client


@pytest.fixture
def es(monkeypatch):
    """(private_key, fake_jwks) — JWKS-ში ერთი ES256 გასაღები `es-kid-1`."""
    private, jwk = make_es256_keypair()
    return private, install_jwks(monkeypatch, jwks(jwk))


@pytest.fixture
def http():
    return TestClient(fastapi_app)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def hs256_token(**overrides):
    return jwt.encode(make_claims(**overrides), HS_SECRET, algorithm="HS256")


def b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


# ---------------------------------------------------------------- (1) ლოკალური გზა: Auth server-ის გარეშე

def test_es256_token_skips_get_user(es, fake, http):
    private, _ = es
    token = sign(private)
    res = http.get("/shops/me", headers=bearer(token))
    assert res.status_code == 200
    assert fake.auth.calls == []
    assert fake.postgrest.tokens == [token]
    assert fake.created == 1


# ---------------------------------------------------------------- (2) CurrentAuth-ის claims

def test_current_auth_has_verified_claims(es, fake):
    private, _ = es
    token = sign(private)
    auth = security.get_current_auth("Bearer " + token)
    assert auth.user_id == USER_SUB
    assert auth.email == USER_EMAIL
    assert auth.claims["aal"] == "aal1"
    assert auth.verified_by == "local"
    assert auth.token == token
    assert auth.client is fake
    assert token not in repr(auth)  # token repr-ში (ლოგში / traceback-ში) არ ხვდება


def test_current_auth_defaults_for_manual_construction():
    """ტესტების override-ები `CurrentAuth(user_id, email, client)`-ით უცვლელად მუშაობს."""
    auth = security.CurrentAuth(user_id="u", email=None, client=object())
    assert auth.claims == {}
    assert auth.token == ""
    assert auth.verified_by == "network"


# ---------------------------------------------------------------- (3) ცხადად არასწორი token -> 401, ქსელის გარეშე

def _expired(private):
    return sign(private, make_claims(exp=int(time.time()) - 3600))


def _wrong_aud(private):
    return sign(private, make_claims(aud="anon"))


def _bad_signature(private):
    other, _ = make_es256_keypair(kid="es-kid-1")  # იგივე kid, სხვა გასაღები
    return sign(other)


def _alg_none(private):
    return f"{b64({'alg': 'none', 'typ': 'JWT', 'kid': 'es-kid-1'})}.{b64(make_claims())}."


def _garbage(private):
    return "not-a-jwt"


@pytest.mark.parametrize("make_token", [_expired, _wrong_aud, _bad_signature, _alg_none, _garbage])
def test_invalid_token_rejected_without_network(es, fake, http, make_token):
    private, _ = es
    res = http.get("/shops/me", headers=bearer(make_token(private)))
    assert res.status_code == 401
    assert res.json()["detail"] == INVALID_DETAIL
    assert res.headers["WWW-Authenticate"] == "Bearer"
    assert fake.auth.calls == []
    assert fake.created == 0  # 401 `create_client`-მდე
    assert fake.postgrest.tokens == []


def test_missing_authorization_header_still_401(es, fake, http):
    res = http.get("/shops/me")
    assert res.status_code == 401
    assert fake.auth.calls == []


# ---------------------------------------------------------------- (4) HS256 -> ძველი ქსელური გზა

def test_hs256_token_uses_get_user_and_unverified_claims(es, fake):
    token = hs256_token()
    auth = security.get_current_auth("Bearer " + token)
    assert fake.auth.calls == [token]
    assert fake.postgrest.tokens == [token]
    assert auth.verified_by == "network"
    assert auth.user_id == USER_SUB
    assert auth.email == USER_EMAIL
    assert auth.claims["aal"] == "aal1"
    assert auth.token == token


def test_hs256_claims_dropped_when_sub_differs_from_user(es, fake):
    fake.auth.user = SimpleNamespace(id="33333333-3333-3333-3333-333333333333", email="x@test.local")
    auth = security.get_current_auth("Bearer " + hs256_token())
    assert auth.claims == {}
    assert auth.user_id == "33333333-3333-3333-3333-333333333333"
    assert auth.verified_by == "network"


def test_hs256_get_user_error_is_401(es, fake, http):
    fake.auth.error = RuntimeError("expired / revoked")
    res = http.get("/shops/me", headers=bearer(hs256_token()))
    assert res.status_code == 401
    assert res.json()["detail"] == INVALID_DETAIL
    assert res.headers["WWW-Authenticate"] == "Bearer"
    assert len(fake.auth.calls) == 1


def test_hs256_no_user_is_401(es, fake, http):
    fake.auth.no_user = True
    res = http.get("/shops/me", headers=bearer(hs256_token()))
    assert res.status_code == 401
    assert res.json()["detail"] == NO_USER_DETAIL
    assert res.headers["WWW-Authenticate"] == "Bearer"
    assert fake.postgrest.tokens == []


# ---------------------------------------------------------------- (5) უცნობი kid, (6) JWKS-ის შეცდომა, (7) გამორთვა

def test_unknown_kid_refreshes_jwks_then_uses_get_user(monkeypatch, fake, http):
    private, _ = make_es256_keypair(kid="rotated-kid")
    _, other_jwk = make_es256_keypair(kid="es-kid-1")
    fake_jwks = install_jwks(monkeypatch, jwks(other_jwk))
    token = sign(private, kid="rotated-kid")
    res = http.get("/shops/me", headers=bearer(token))
    assert res.status_code == 200
    assert fake_jwks.calls == 2  # cache + ერთი იძულებითი refresh
    assert fake.auth.calls == [token]
    assert fake.postgrest.tokens == [token]


def test_jwks_network_error_falls_back_to_get_user(monkeypatch, fake, http):
    private, _ = make_es256_keypair()
    install_jwks(monkeypatch, OSError("jwks down"))
    token = sign(private)
    res = http.get("/shops/me", headers=bearer(token))
    assert res.status_code == 200
    assert fake.auth.calls == [token]


def test_jwt_local_verify_false_uses_get_user_for_es256(es, fake, http, cfg):
    private, fake_jwks = es
    cfg.jwt_local_verify = False
    token = sign(private)
    res = http.get("/shops/me", headers=bearer(token))
    assert res.status_code == 200
    assert fake.auth.calls == [token]
    assert fake_jwks.calls == 0


# ---------------------------------------------------------------- confirm_with_auth_server

def test_confirm_with_auth_server_ok(es, fake):
    private, _ = es
    auth = security.get_current_auth("Bearer " + sign(private))
    security.confirm_with_auth_server(auth)
    assert fake.auth.calls == [auth.token]


@pytest.mark.parametrize("break_it", ["error", "no_user", "other_user"])
def test_confirm_with_auth_server_rejects(es, fake, break_it):
    private, _ = es
    auth = security.get_current_auth("Bearer " + sign(private))
    if break_it == "error":
        fake.auth.error = RuntimeError("signed out")
    elif break_it == "no_user":
        fake.auth.no_user = True
    else:
        fake.auth.user = SimpleNamespace(id="33333333-3333-3333-3333-333333333333", email=None)
    with pytest.raises(HTTPException) as exc:
        security.confirm_with_auth_server(auth)
    assert exc.value.status_code == 401
    assert exc.value.detail == INVALID_DETAIL
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}


# ---------------------------------------------------------------- (8) ადმინი ყოველთვის Auth server-ითაც

def test_admin_always_confirms_with_auth_server(es, fake, http):
    private, _ = es
    fake.auth.user = SimpleNamespace(id=ADMIN_SUB, email="admin@test.local")
    token = sign(private, make_claims(sub=ADMIN_SUB))
    res = http.get("/admin/check", headers=bearer(token))
    assert res.status_code == 200
    assert res.json() == {"is_admin": True}
    assert fake.auth.calls == [token]  # ზუსტად 1


def test_admin_signed_out_token_is_rejected(es, fake, http):
    private, _ = es
    fake.auth.error = RuntimeError("session revoked")
    res = http.get("/admin/check", headers=bearer(sign(private, make_claims(sub=ADMIN_SUB))))
    assert res.status_code == 401
    assert res.json()["detail"] == INVALID_DETAIL
    assert len(fake.auth.calls) == 1


def test_admin_confirm_returns_other_user_is_rejected(es, fake, http):
    private, _ = es
    fake.auth.user = SimpleNamespace(id=USER_SUB, email=None)
    res = http.get("/admin/check", headers=bearer(sign(private, make_claims(sub=ADMIN_SUB))))
    assert res.status_code == 401


def test_non_admin_es256_gets_403_without_network(es, fake, http):
    private, _ = es
    res = http.get("/admin/check", headers=bearer(sign(private)))
    assert res.status_code == 403
    assert fake.auth.calls == []


def test_admin_hs256_calls_get_user_exactly_once(es, fake, http):
    fake.auth.user = SimpleNamespace(id=ADMIN_SUB, email="admin@test.local")
    token = hs256_token(sub=ADMIN_SUB)
    res = http.get("/admin/check", headers=bearer(token))
    assert res.status_code == 200
    assert fake.auth.calls == [token]  # get_current_auth-ში უკვე ქსელურია -> მეორედ არა


def test_admin_when_local_verify_disabled_calls_get_user_once(es, fake, http, cfg):
    private, _ = es
    cfg.jwt_local_verify = False
    fake.auth.user = SimpleNamespace(id=ADMIN_SUB, email="admin@test.local")
    res = http.get("/admin/check", headers=bearer(sign(private, make_claims(sub=ADMIN_SUB))))
    assert res.status_code == 200
    assert len(fake.auth.calls) == 1


# ---------------------------------------------------------------- (9) ლოგი

def test_logs_never_contain_token_sub_or_email(es, fake, http, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    private, _ = es
    tokens = [
        sign(private),                                   # ლოკალური
        sign(private, make_claims(exp=int(time.time()) - 3600)),  # 401
        hs256_token(),                                   # ქსელური
        sign(private, make_claims(sub=ADMIN_SUB)),       # ადმინი
    ]
    fake.auth.user = SimpleNamespace(id=USER_SUB, email=USER_EMAIL)
    for token in tokens:
        http.get("/shops/me", headers=bearer(token))
    fake.auth.user = SimpleNamespace(id=ADMIN_SUB, email="admin@test.local")
    http.get("/admin/check", headers=bearer(tokens[3]))
    fake.auth.error = RuntimeError(f"boom {tokens[0]}")
    http.get("/admin/check", headers=bearer(tokens[3]))
    # JWKS-ის შეცდომის გზაც
    jwt_verify._reset_for_tests()
    install_jwks(monkeypatch, OSError("jwks down"))
    fake.auth.error = None
    fake.auth.user = SimpleNamespace(id=USER_SUB, email=USER_EMAIL)
    http.get("/shops/me", headers=bearer(tokens[0]))

    text = caplog.text
    assert caplog.records  # ლოგი რეალურად იწერება (jwt_verify-ის INFO / WARNING)
    for secret in (*tokens, USER_SUB, ADMIN_SUB, USER_EMAIL, "admin@test.local"):
        assert secret not in text
