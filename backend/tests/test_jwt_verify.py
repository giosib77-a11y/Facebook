"""Stage 22 (A-046): `core/jwt_verify` — ES256/RS256 ლოკალური შემოწმება JWKS-ით.

ტესტი ქსელს არ მიმართავს: JWKS — `jwt.PyJWKClient.fetch_data`-ის fake (გამოძახებების მთვლელით);
გასაღებები — `cryptography`-ით გენერირებული EC P-256 / RSA-2048. ქვემოთა helper-ებს
(`make_es256_keypair`, `make_rs256_keypair`, `make_claims`, `sign`, `install_jwks`, `jwk_for`) S22-8 აიმპორტებს.
"""
import base64
import json
import logging
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.core import jwt_verify
from app.core.jwt_verify import InvalidToken, unverified_claims, verify

SUPABASE_URL = "https://proj.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
USER_SUB = "22222222-2222-2222-2222-222222222222"
USER_EMAIL = "seller-secret@example.com"


# ---------------------------------------------------------------- helpers (S22-8 იყენებს)

def jwk_for(public_key, kid: str, alg: str, use: str | None = "sig") -> dict:
    algorithm = jwt.algorithms.ECAlgorithm if alg.startswith("ES") else jwt.algorithms.RSAAlgorithm
    jwk = algorithm.to_jwk(public_key, as_dict=True)
    jwk.update({"kid": kid, "alg": alg})
    if use is not None:
        jwk["use"] = use
    return jwk


def make_es256_keypair(kid: str = "es-kid-1"):
    """(private_key, jwk) — EC P-256; jwk JWKS-ში ჩასასმელად (`{"keys": [jwk]}`)."""
    private = ec.generate_private_key(ec.SECP256R1())
    return private, jwk_for(private.public_key(), kid, "ES256")


def make_rs256_keypair(kid: str = "rs-kid-1"):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, jwk_for(private.public_key(), kid, "RS256")


def make_claims(**overrides) -> dict:
    """ვალიდური Supabase access token-ის claims; `None` მნიშვნელობა claim-ს აშორებს."""
    now = int(time.time())
    claims = {
        "iss": ISSUER, "aud": "authenticated", "sub": USER_SUB, "email": USER_EMAIL,
        "role": "authenticated", "aal": "aal1", "iat": now, "exp": now + 3600,
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def sign(private_key, claims: dict | None = None, alg: str = "ES256", kid: str | None = "es-kid-1") -> str:
    headers = {"kid": kid} if kid is not None else None
    return jwt.encode(make_claims() if claims is None else claims, private_key, algorithm=alg, headers=headers)


class FakeJwks:
    """`PyJWKClient.fetch_data`-ის ჩანაცვლება: პასუხები რიგით (ბოლო მეორდება); Exception-ს ისვრის."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self):
        item = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if isinstance(item, BaseException):
            raise item
        return item


def install_jwks(monkeypatch, *responses) -> FakeJwks:
    """responses: JWKS dict-ები (`{"keys": [...]}`) ან exception-ები."""
    fake = FakeJwks(*responses)
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fake)
    return fake


def jwks(*keys) -> dict:
    return {"keys": list(keys)}


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    """ტესტის settings (supabase_url + ლოკალური შემოწმება ჩართული) და სუფთა module state."""
    jwt_verify._reset_for_tests()
    settings = SimpleNamespace(supabase_url=SUPABASE_URL, jwt_local_verify=True)
    monkeypatch.setattr(jwt_verify, "get_settings", lambda: settings)
    yield settings
    jwt_verify._reset_for_tests()


@pytest.fixture
def es(monkeypatch):
    """(private_key, fake_jwks) — JWKS-ში ერთი ES256 გასაღები `es-kid-1`."""
    private, jwk = make_es256_keypair()
    return private, install_jwks(monkeypatch, jwks(jwk))


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


# ---------------------------------------------------------------- წარმატებული შემოწმება

def test_valid_es256_returns_claims(es):
    private, fake = es
    claims = verify(sign(private))
    assert claims["sub"] == USER_SUB
    assert claims["email"] == USER_EMAIL
    assert claims["aal"] == "aal1"
    assert fake.calls == 1


def test_valid_rs256(monkeypatch):
    private, jwk = make_rs256_keypair()
    install_jwks(monkeypatch, jwks(jwk))
    claims = verify(sign(private, alg="RS256", kid="rs-kid-1"))
    assert claims["sub"] == USER_SUB


def test_expired_within_leeway_ok(es):
    private, _ = es
    token = sign(private, make_claims(exp=int(time.time()) - 10))
    assert verify(token)["sub"] == USER_SUB


def test_issuer_trailing_slash_in_url_is_tolerated(es, cfg):
    private, _ = es
    cfg.supabase_url = SUPABASE_URL + "/"
    assert verify(sign(private))["sub"] == USER_SUB


# ---------------------------------------------------------------- ცუდი token -> InvalidToken (fallback-ის გარეშე)

def test_expired_raises(es):
    private, _ = es
    token = sign(private, make_claims(exp=int(time.time()) - 31))
    with pytest.raises(InvalidToken):
        verify(token)


def test_wrong_aud_raises(es):
    private, _ = es
    with pytest.raises(InvalidToken):
        verify(sign(private, make_claims(aud="anon")))


def test_wrong_iss_raises(es):
    private, _ = es
    with pytest.raises(InvalidToken):
        verify(sign(private, make_claims(iss="https://evil.supabase.co/auth/v1")))


@pytest.mark.parametrize("missing", ["exp", "sub", "aud", "iss"])
def test_missing_exp_or_sub_raises(es, missing):
    private, _ = es
    with pytest.raises(InvalidToken):
        verify(sign(private, make_claims(**{missing: None})))


def test_empty_sub_raises(es):
    private, _ = es
    with pytest.raises(InvalidToken):
        verify(sign(private, make_claims(sub="")))


def test_bad_signature_raises(es):
    other_private, _ = make_es256_keypair()  # სხვა გასაღები, იგივე kid
    with pytest.raises(InvalidToken):
        verify(sign(other_private))


def test_alg_none_raises(es):
    _, fake = es
    token = f"{_b64({'alg': 'none', 'kid': 'es-kid-1'})}.{_b64(make_claims())}."
    with pytest.raises(InvalidToken):
        verify(token)
    assert fake.calls == 0


@pytest.mark.parametrize("alg", ["HS512", "PS256"])
def test_other_alg_raises(es, alg):
    _, fake = es
    if alg == "HS512":
        token = jwt.encode(make_claims(), "x" * 64, algorithm="HS512", headers={"kid": "es-kid-1"})
    else:
        rsa_private, _ = make_rs256_keypair()
        token = jwt.encode(make_claims(), rsa_private, algorithm="PS256", headers={"kid": "es-kid-1"})
    with pytest.raises(InvalidToken):
        verify(token)
    assert fake.calls == 0


def test_garbage_token_raises(es):
    _, fake = es
    for token in ("not-a-jwt", "a.b.c", "....", "x" * 50):
        with pytest.raises(InvalidToken):
            verify(token)
    assert fake.calls == 0


def test_jwk_alg_mismatch_raises(monkeypatch):
    # header ES256, მაგრამ იგივე kid JWKS-ში RSA გასაღებია
    es_private, _ = make_es256_keypair(kid="shared-kid")
    _, rsa_jwk = make_rs256_keypair(kid="shared-kid")
    install_jwks(monkeypatch, jwks(rsa_jwk))
    with pytest.raises(InvalidToken):
        verify(sign(es_private, kid="shared-kid"))


def test_jwk_use_enc_raises(monkeypatch):
    private, _ = make_es256_keypair()
    install_jwks(monkeypatch, jwks(jwk_for(private.public_key(), "es-kid-1", "ES256", use="enc")))
    with pytest.raises(InvalidToken):
        verify(sign(private))


# ---------------------------------------------------------------- None = „ქსელური get_user"

def test_hs256_returns_none_without_fetch(es):
    _, fake = es
    token = jwt.encode(make_claims(), "s" * 64, algorithm="HS256")
    assert verify(token) is None
    # kid-ითაც (migrate-ის შემდეგ legacy secret-საც შეიძლება ჰქონდეს kid; JWKS-ში არ ქვეყნდება)
    token_kid = jwt.encode(make_claims(), "s" * 64, algorithm="HS256", headers={"kid": "es-kid-1"})
    assert verify(token_kid) is None
    assert fake.calls == 0


def test_no_kid_returns_none(es):
    private, fake = es
    assert verify(sign(private, kid=None)) is None
    assert fake.calls == 0


def test_non_string_kid_raises(es):
    # PyJWT თავად უარყოფს არა-str kid-ს header-ის დონეზე; ასეთი token არასდროს არის ლეგიტიმური
    private, fake = es
    token = jwt.encode(make_claims(), private, algorithm="ES256", headers={"kid": "es-kid-1"})
    forged = _b64({"alg": "ES256", "typ": "JWT", "kid": 123}) + "." + token.split(".", 1)[1]
    with pytest.raises(InvalidToken):
        verify(forged)
    assert fake.calls == 0


def test_disabled_or_no_url_returns_none(es, cfg):
    private, fake = es
    token = sign(private)
    cfg.jwt_local_verify = False
    assert verify(token) is None
    cfg.jwt_local_verify = True
    cfg.supabase_url = ""
    assert verify(token) is None
    assert fake.calls == 0


def test_unknown_kid_refetches_once_then_none(es, caplog):
    private, fake = es
    with caplog.at_level(logging.INFO, logger="app"):
        assert verify(sign(private, kid="unknown-1")) is None
        assert fake.calls == 2  # cache miss + ერთი იძულებითი refresh
        # 60 წმ-ში მეორე უცნობი kid -> ახალი მოთხოვნა JWKS-ზე აღარ
        assert verify(sign(private, kid="unknown-2")) is None
        assert fake.calls == 2
    assert "unknown-1" not in caplog.text and "unknown-2" not in caplog.text


def test_refresh_allowed_again_after_interval(es, monkeypatch):
    private, fake = es
    now = [1000.0]
    monkeypatch.setattr(jwt_verify, "_monotonic", lambda: now[0])
    assert verify(sign(private, kid="unknown-1")) is None
    assert fake.calls == 2
    now[0] += jwt_verify.REFRESH_MIN_INTERVAL_SECONDS + 1
    assert verify(sign(private, kid="unknown-2")) is None
    assert fake.calls == 3


def test_rotated_key_found_after_refresh(monkeypatch):
    old_private, old_jwk = make_es256_keypair(kid="old")
    new_private, new_jwk = make_es256_keypair(kid="new")
    fake = install_jwks(monkeypatch, jwks(old_jwk), jwks(old_jwk, new_jwk))
    assert verify(sign(old_private, kid="old"))["sub"] == USER_SUB
    assert fake.calls == 1
    assert verify(sign(new_private, kid="new"))["sub"] == USER_SUB
    assert fake.calls == 2


def test_jwks_network_error_returns_none(monkeypatch, caplog):
    private, _ = make_es256_keypair()
    fake = install_jwks(monkeypatch, jwt.PyJWKClientConnectionError("down"))
    with caplog.at_level(logging.INFO, logger="app"):
        assert verify(sign(private)) is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "PyJWKClientConnectionError" in warnings[0].getMessage()
    assert fake.calls == 1


@pytest.mark.parametrize("failure", [
    jwt.PyJWKSetError("empty"), OSError("boom"), ValueError("bad json"), TimeoutError("slow"),
    {"keys": []}, {"no": "keys"},
])
def test_jwks_any_failure_returns_none_never_invalid(monkeypatch, failure):
    private, _ = make_es256_keypair()
    install_jwks(monkeypatch, failure)
    assert verify(sign(private)) is None


def test_jwks_error_backoff(monkeypatch):
    private, jwk = make_es256_keypair()
    fake = install_jwks(monkeypatch, jwt.PyJWKClientConnectionError("down"), jwks(jwk))
    now = [1000.0]
    monkeypatch.setattr(jwt_verify, "_monotonic", lambda: now[0])
    token = sign(private)
    assert verify(token) is None
    assert fake.calls == 1
    # ავარიის დროს ყოველი მოთხოვნა 5 წმ timeout-ს არ ელოდება
    assert verify(token) is None
    assert fake.calls == 1
    now[0] += jwt_verify.JWKS_ERROR_BACKOFF_SECONDS + 1
    assert verify(token)["sub"] == USER_SUB
    assert fake.calls == 2


def test_jwks_cached(es):
    private, fake = es
    token = sign(private)
    verify(token)
    verify(token)
    assert fake.calls == 1


def test_client_configuration(es):
    private, _ = es
    verify(sign(private))
    client = jwt_verify._client()
    assert client.uri == f"{ISSUER}/.well-known/jwks.json"
    assert client.timeout == jwt_verify.JWKS_TIMEOUT_SECONDS == 5
    assert client.jwk_set_cache.lifespan == jwt_verify.JWKS_LIFESPAN_SECONDS == 300
    assert jwt_verify._client() is client  # module-level, ერთი instance


def test_client_rebuilt_when_url_changes(es, cfg):
    first = jwt_verify._client()
    cfg.supabase_url = "https://other.supabase.co"
    second = jwt_verify._client()
    assert second is not first
    assert second.uri == "https://other.supabase.co/auth/v1/.well-known/jwks.json"


# ---------------------------------------------------------------- ლოგი და unverified_claims

def test_active_logged_once(es, caplog):
    private, _ = es
    with caplog.at_level(logging.INFO, logger="app"):
        verify(sign(private))
        verify(sign(private))
    active = [m for m in caplog.messages if "local verification active" in m]
    assert active == ["jwt: local verification active (alg=ES256, kid=es-kid-1)"]


def test_logs_never_contain_token_or_sub(monkeypatch, caplog):
    private, jwk = make_es256_keypair()
    fake = install_jwks(monkeypatch, jwks(jwk))
    good = sign(private)
    bad = sign(make_es256_keypair()[0], make_claims(aud="anon"))
    unknown = sign(private, kid="attacker-chosen-kid")
    with caplog.at_level(logging.DEBUG, logger="app"):
        verify(good)
        with pytest.raises(InvalidToken):
            verify(bad)
        assert verify(unknown) is None
        fake.responses = [OSError("down")]
        fake.calls = 0
        jwt_verify._reset_for_tests()
        assert verify(good) is None
    text = caplog.text
    assert text  # ლოგი რეალურად შეგროვდა
    for secret in (good, bad, unknown, USER_SUB, USER_EMAIL, "attacker-chosen-kid",
                   good.split(".")[1], good.split(".")[2]):
        assert secret not in text


def test_unverified_claims(es):
    private, _ = es
    claims = unverified_claims(sign(private))
    assert claims["sub"] == USER_SUB and claims["aal"] == "aal1"
    # ვადაგასული token-ის claims-საც კითხულობს (ხელმოწერა ამ ეტაპზე უკვე Auth-მა დაადასტურა)
    assert unverified_claims(sign(private, make_claims(exp=int(time.time()) - 5000)))["sub"] == USER_SUB
    for garbage in ("", "not-a-jwt", "a.b.c", "....", "x" * 100):
        assert unverified_claims(garbage) == {}
