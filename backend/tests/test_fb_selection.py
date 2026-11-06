"""A-045 (N-09): page-selection token (Fernet + HKDF `chatassist:fb-page-selection:v1`, 10 min)."""
import base64
import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

import app.core.crypto as crypto
from app.services import fb_selection as sel

SECRET = "test-secret"
USER = "1234567890"
SHOP = "11111111-1111-1111-1111-111111111111"
USER_TOKEN = "EAAB-SECRET-USER-TOKEN-xyz"
PAGES = ["100", "200", "300"]
PAGE_KEY = Fernet.generate_key().decode()


def _settings(secret: str = SECRET):
    return SimpleNamespace(fb_app_secret=secret, fb_token_encryption_key=PAGE_KEY)


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(crypto, "get_settings", lambda: _settings())


def _make(pages=None) -> str:
    return sel.make(USER, SHOP, USER_TOKEN, PAGES if pages is None else pages)


def _ts(token: str) -> int:
    return sel._fernet().extract_timestamp(token)


def _assert_kind(token: str, kind: str, user: str = USER, **kwargs) -> None:
    with pytest.raises(sel.SelectionError) as exc:
        sel.read(token, user, **kwargs)
    assert exc.value.kind == kind


def test_constants():
    assert sel.TTL_SECONDS == 600
    assert sel.MAX_PAGES == 25
    assert sel.MAX_TOKEN_CHARS == 4096
    assert crypto.KEY_FB_PAGE_SELECTION == "fb-page-selection:v1"


def test_roundtrip():
    data = sel.read(_make(), USER)
    assert data == {"v": 1, "uid": USER, "shop": SHOP, "ut": USER_TOKEN, "pages": PAGES}


def test_user_token_not_visible_in_token():
    token = _make()
    assert USER_TOKEN not in token
    raw = base64.urlsafe_b64decode(token.encode())
    assert USER_TOKEN.encode() not in raw
    assert b"EAAB" not in raw
    assert SHOP.encode() not in raw


def test_tampered_token_is_invalid():
    token = _make()
    i = len(token) // 2
    bad = token[:i] + ("A" if token[i] != "A" else "B") + token[i + 1 :]
    _assert_kind(bad, "invalid")


@pytest.mark.parametrize("bad", ["", "garbage", "not base64 !!!", "a" * 100, "გვერდი", None, 123])
def test_garbage_is_invalid(bad):
    _assert_kind(bad, "invalid")


def test_other_app_secret_is_invalid(monkeypatch):
    token = _make()
    monkeypatch.setattr(crypto, "get_settings", lambda: _settings("another-secret"))
    _assert_kind(token, "invalid")


def test_page_token_key_token_is_invalid(monkeypatch):
    # encrypted with the page-token key (FB_TOKEN_ENCRYPTION_KEY) - domain separation
    monkeypatch.setattr(crypto, "get_settings", lambda: _settings())
    payload = json.dumps(
        {"v": 1, "uid": USER, "shop": SHOP, "ut": USER_TOKEN, "pages": PAGES}, separators=(",", ":")
    )
    foreign = crypto.encrypt(payload)
    _assert_kind(foreign, "invalid")


def test_expiry_boundary():
    token = _make()
    ts = _ts(token)
    assert sel.read(token, USER, now=ts + 599)["shop"] == SHOP
    assert sel.read(token, USER, now=ts + 600)["shop"] == SHOP
    _assert_kind(token, "expired", now=ts + 601)


def test_expired_uses_wall_clock_by_default(monkeypatch):
    token = _make()
    ts = _ts(token)
    monkeypatch.setattr(sel.time, "time", lambda: ts + 3600)
    _assert_kind(token, "expired")


def test_future_token_is_invalid():
    token = _make()
    ts = _ts(token)
    _assert_kind(token, "invalid", now=ts - 120)
    # small clock skew is tolerated
    assert sel.read(token, USER, now=ts - 30)["uid"] == USER


def test_other_user_is_invalid_same_kind():
    token = _make()
    _assert_kind(token, "invalid", user="999")


def test_other_user_and_expired_reports_expired_first():
    # expiry is checked before the payload is decrypted, so no information about the owner leaks
    token = _make()
    _assert_kind(token, "expired", user="999", now=_ts(token) + 601)


def test_oversized_token_rejected_before_decrypt(monkeypatch):
    def boom():
        raise AssertionError("must not decrypt an oversized token")

    monkeypatch.setattr(sel, "_fernet", boom)
    _assert_kind("A" * (sel.MAX_TOKEN_CHARS + 1), "invalid")


@pytest.mark.parametrize("pages", [[], [str(i) for i in range(26)]])
def test_make_page_count_bounds(pages):
    with pytest.raises(ValueError):
        sel.make(USER, SHOP, USER_TOKEN, pages)


def test_make_accepts_bounds():
    for n in (1, 25):
        pages = [str(i) for i in range(n)]
        assert sel.read(sel.make(USER, SHOP, USER_TOKEN, pages), USER)["pages"] == pages


def test_empty_secret_fails_closed(monkeypatch):
    token = _make()
    monkeypatch.setattr(crypto, "get_settings", lambda: _settings(""))
    with pytest.raises(RuntimeError):
        sel.make(USER, SHOP, USER_TOKEN, PAGES)
    with pytest.raises(RuntimeError):
        sel.read(token, USER)


def test_derived_key_is_separate():
    key = crypto.derive_key(crypto.KEY_FB_PAGE_SELECTION)
    assert len(key) == 32
    assert key != crypto.derive_key(crypto.KEY_OAUTH_STATE)
    assert key != crypto.derive_key(crypto.KEY_DELETION_CODE)


@pytest.mark.parametrize(
    "payload",
    [
        {"v": 2, "uid": USER, "shop": SHOP, "ut": "t", "pages": ["1"]},
        {"uid": USER, "shop": SHOP, "ut": "t", "pages": ["1"]},
        {"v": 1, "uid": "", "shop": SHOP, "ut": "t", "pages": ["1"]},
        {"v": 1, "uid": USER, "shop": "", "ut": "t", "pages": ["1"]},
        {"v": 1, "uid": USER, "shop": SHOP, "ut": "", "pages": ["1"]},
        {"v": 1, "uid": USER, "shop": SHOP, "ut": 5, "pages": ["1"]},
        {"v": 1, "uid": USER, "shop": SHOP, "ut": "t", "pages": []},
        {"v": 1, "uid": USER, "shop": SHOP, "ut": "t", "pages": [1, 2]},
        {"v": 1, "uid": USER, "shop": SHOP, "ut": "t", "pages": "123"},
        {"v": 1, "uid": USER, "shop": SHOP, "ut": "t", "pages": [str(i) for i in range(26)]},
        ["not", "a", "dict"],
    ],
)
def test_validly_encrypted_but_malformed_payload_is_invalid(payload):
    token = sel._fernet().encrypt(json.dumps(payload).encode()).decode()
    _assert_kind(token, "invalid")


def test_validly_encrypted_non_json_is_invalid():
    token = sel._fernet().encrypt(b"not json").decode()
    _assert_kind(token, "invalid")
    token = sel._fernet().encrypt(b"\xff\xfe").decode()
    _assert_kind(token, "invalid")
