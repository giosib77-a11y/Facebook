"""A-047 (N-18): HKDF-derived keys for OAuth state and deletion code.

Before: the OAuth state HMAC, the deletion-code hash and the deletion-code HMAC all used the
raw FB_APP_SECRET - the same key Meta uses for X-Hub-Signature-256 / appsecret_proof /
signed_request. Now each purpose gets its own key derived from the secret via HKDF.
Meta-facing formulas (appsecret_proof, X-Hub-Signature-256, signed_request) stay on the raw secret.
"""
import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import app.api.facebook as api_fb
import app.core.crypto as crypto
import app.services.facebook as fb

SECRET = "hkdf-test-app-secret"
DAY = 24 * 3600


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    s = SimpleNamespace(fb_app_secret=SECRET)
    for m in (crypto, fb, api_fb):
        monkeypatch.setattr(m, "get_settings", lambda: s)


def _hkdf(secret: str, label: str) -> bytes:
    """Independent reference implementation of the spec (not via crypto.derive_key)."""
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"chatassist:" + label.encode()
    ).derive(secret.encode())


# ---------------------------------------------------------------------------
# derive_key
# ---------------------------------------------------------------------------
def test_labels_are_versioned_constants():
    assert crypto.KEY_OAUTH_STATE == "oauth-state:v1"
    assert crypto.KEY_DELETION_CODE == "deletion-code:v1"


def test_derive_key_matches_spec_and_is_32_bytes():
    key = crypto.derive_key(crypto.KEY_OAUTH_STATE)
    assert isinstance(key, bytes) and len(key) == 32
    assert key == _hkdf(SECRET, "oauth-state:v1")


def test_derive_key_is_deterministic():
    assert crypto.derive_key("x:v1") == crypto.derive_key("x:v1")


def test_derive_key_labels_differ_and_differ_from_raw_secret():
    a = crypto.derive_key(crypto.KEY_OAUTH_STATE)
    b = crypto.derive_key(crypto.KEY_DELETION_CODE)
    assert a != b
    assert SECRET.encode() not in (a, b)


def test_derive_key_other_secret_other_key(monkeypatch):
    before = crypto.derive_key(crypto.KEY_OAUTH_STATE)
    monkeypatch.setattr(crypto, "get_settings", lambda: SimpleNamespace(fb_app_secret="another"))
    assert crypto.derive_key(crypto.KEY_OAUTH_STATE) != before


def test_derive_key_empty_secret_raises(monkeypatch):
    monkeypatch.setattr(crypto, "get_settings", lambda: SimpleNamespace(fb_app_secret=""))
    with pytest.raises(RuntimeError, match="FB_APP_SECRET is not configured"):
        crypto.derive_key(crypto.KEY_OAUTH_STATE)


def test_derive_key_never_falls_back_when_explicit_secret_empty():
    # settings HAVE a secret, but the caller passed an empty one -> still fail closed
    with pytest.raises(RuntimeError):
        crypto.derive_key(crypto.KEY_OAUTH_STATE, secret="")


# ---------------------------------------------------------------------------
# OAuth state
# ---------------------------------------------------------------------------
def _raw_state(data: dict, key: bytes) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    return f"{raw}.{hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()}"


def test_state_round_trip():
    state = fb.sign_state({"shop_id": "s", "ts": time.time()})
    assert fb.verify_state(state)["shop_id"] == "s"


def test_state_not_signed_with_raw_app_secret():
    # old formula: HMAC straight with the raw secret -> must now be rejected
    # (state TTL is 10 min: a connect started during deploy -> invalid_state, just retry)
    old = _raw_state({"shop_id": "s", "ts": time.time()}, SECRET.encode())
    assert fb.verify_state(old) is None
    # and the new state's signature is not the raw-secret HMAC
    new = fb.sign_state({"shop_id": "s", "ts": 1})
    raw, sig = new.rsplit(".", 1)
    assert sig != hmac.new(SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    assert sig == hmac.new(_hkdf(SECRET, "oauth-state:v1"), raw.encode(), hashlib.sha256).hexdigest()


def test_state_signed_with_deletion_key_is_rejected():
    forged = _raw_state({"shop_id": "s", "ts": time.time()}, _hkdf(SECRET, "deletion-code:v1"))
    assert fb.verify_state(forged) is None


def test_state_expired_still_rejected():
    state = fb.sign_state({"shop_id": "s", "ts": time.time() - 601})
    assert fb.verify_state(state) is None


# ---------------------------------------------------------------------------
# Deletion code
# ---------------------------------------------------------------------------
def _legacy_code(user_id: str, ts: int) -> str:
    """The pre-HKDF formula, built with the raw secret (as issued before this change)."""
    secret = SECRET.encode()
    uid_hash = hashlib.sha256(str(user_id).encode() + secret).hexdigest()[:12]
    raw = base64.urlsafe_b64encode(f"{uid_hash}:{ts}".encode()).decode().rstrip("=")
    return f"{raw}.{hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest()[:16]}"


def _decode(code: str) -> tuple[str, int]:
    raw = code.rsplit(".", 1)[0]
    uid_hash, ts = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode().split(":")
    return uid_hash, int(ts)


def test_new_deletion_code_uses_derived_key():
    key = _hkdf(SECRET, "deletion-code:v1")
    code = api_fb.make_deletion_code("1234567890")
    raw, sig = code.rsplit(".", 1)
    assert sig != hmac.new(SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()[:16]
    assert sig == hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()[:16]
    # uid hash also uses the derived key; the format is unchanged (12 hex chars)
    uid_hash, _ts = _decode(code)
    assert uid_hash == hashlib.sha256(b"1234567890" + key).hexdigest()[:12]
    assert api_fb.verify_deletion_code(code) is not None


def test_new_deletion_code_verifies_and_reports_requested_at():
    code = api_fb.make_deletion_code("42")
    info = api_fb.verify_deletion_code(code)
    assert info and info["requested_at"].startswith("20")


def test_legacy_deletion_code_still_verifies():
    ts = int(time.time()) - 30 * DAY
    info = api_fb.verify_deletion_code(_legacy_code("1234567890", ts))
    assert info is not None
    assert info["requested_at"].startswith(
        time.strftime("%Y-%m-%d", time.gmtime(ts))
    )


def test_legacy_deletion_code_older_than_ttl_is_rejected():
    ts = int(time.time()) - 401 * DAY
    assert api_fb.verify_deletion_code(_legacy_code("1234567890", ts)) is None


def test_new_deletion_code_older_than_ttl_is_rejected():
    key = _hkdf(SECRET, "deletion-code:v1")
    raw = base64.urlsafe_b64encode(f"abc:{int(time.time()) - 401 * DAY}".encode()).decode().rstrip("=")
    code = f"{raw}.{hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()[:16]}"
    assert api_fb.verify_deletion_code(code) is None


def test_deletion_code_signed_with_oauth_state_key_is_rejected():
    key = _hkdf(SECRET, "oauth-state:v1")
    raw = base64.urlsafe_b64encode(f"abc:{int(time.time())}".encode()).decode().rstrip("=")
    code = f"{raw}.{hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()[:16]}"
    assert api_fb.verify_deletion_code(code) is None


@pytest.mark.parametrize("bad", ["", "nodot", "a.b", ".", "abc.def.ghi"])
def test_malformed_deletion_codes_are_rejected(bad):
    assert api_fb.verify_deletion_code(bad) is None


def test_tampered_deletion_code_is_rejected():
    code = api_fb.make_deletion_code("42")
    raw, sig = code.rsplit(".", 1)
    flipped = ("0" if sig[0] != "0" else "1") + sig[1:]
    assert api_fb.verify_deletion_code(f"{raw}.{flipped}") is None


# ---------------------------------------------------------------------------
# State and deletion keys are separated
# ---------------------------------------------------------------------------
def test_state_and_deletion_keys_are_separated():
    assert crypto.derive_key(crypto.KEY_OAUTH_STATE) != crypto.derive_key(crypto.KEY_DELETION_CODE)
    # a deletion code's (raw, sig) is not a valid state signature and vice versa
    state_raw, state_sig = fb.sign_state({"ts": time.time()}).rsplit(".", 1)
    deletion_key = crypto.derive_key(crypto.KEY_DELETION_CODE)
    assert state_sig != hmac.new(deletion_key, state_raw.encode(), hashlib.sha256).hexdigest()
    code_raw, code_sig = api_fb.make_deletion_code("42").rsplit(".", 1)
    state_key = crypto.derive_key(crypto.KEY_OAUTH_STATE)
    assert code_sig != hmac.new(state_key, code_raw.encode(), hashlib.sha256).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Meta-facing formulas stay on the raw app secret
# ---------------------------------------------------------------------------
def test_appsecret_proof_unchanged(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    def request(method, url, **kwargs):
        with httpx.Client(transport=transport) as client:
            return client.request(method, url, **kwargs)

    monkeypatch.setattr(httpx, "request", request)
    monkeypatch.setattr(
        fb, "get_settings", lambda: SimpleNamespace(fb_app_secret=SECRET, fb_graph_version="v21.0")
    )
    fb._graph("GET", "/me", params={"access_token": "TOKEN-1"})
    expected = hmac.new(SECRET.encode(), b"TOKEN-1", hashlib.sha256).hexdigest()
    assert seen["params"]["appsecret_proof"] == expected


def test_verify_signature_uses_raw_secret():
    body = b'{"object":"page"}'
    good = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert fb.verify_signature(SECRET, body, good) is True
    derived = "sha256=" + hmac.new(_hkdf(SECRET, "oauth-state:v1"), body, hashlib.sha256).hexdigest()
    assert fb.verify_signature(SECRET, body, derived) is False


def test_parse_signed_request_uses_raw_secret():
    payload = base64.urlsafe_b64encode(json.dumps({"user_id": "1"}).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(
        hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    assert fb.parse_signed_request(f"{sig}.{payload}", SECRET) == {"user_id": "1"}
