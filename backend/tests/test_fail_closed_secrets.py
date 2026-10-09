"""S11-6: empty secrets must fail closed (no HMAC with an empty key, no guessable fallback)."""
import base64
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

import app.api.facebook as api_fb
import app.api.webhook as webhook
import app.services.facebook as fb
from app.config import Settings
from app.main import check_required_settings

BODY = json.dumps({"object": "page", "entry": [{"id": "1", "messaging": []}]}).encode()

ALL_NAMES = [
    "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY", "GEMINI_API_KEY",
    "FB_APP_SECRET", "FB_VERIFY_TOKEN", "FB_TOKEN_ENCRYPTION_KEY",
]


def _prod(**kw) -> Settings:
    return Settings(_env_file=None, app_env="production", **kw)


def _full(**over) -> dict:
    vals = dict(
        supabase_url="https://x.supabase.co", supabase_publishable_key="pk",
        supabase_secret_key="sk", gemini_api_key="g", fb_app_secret="s",
        fb_verify_token="v", fb_token_encryption_key=Fernet.generate_key().decode(),
    )
    vals.update(over)
    return vals


def _no_secret(monkeypatch, *modules):
    for m in modules:
        monkeypatch.setattr(m, "get_settings", lambda: SimpleNamespace(fb_app_secret=""))


# ---- function-level ----
def test_webhook_post_with_empty_key_signature_rejected(client, monkeypatch):
    _no_secret(monkeypatch, webhook)
    calls = []
    monkeypatch.setattr(webhook, "_process_events", lambda d: calls.append(d))
    sig = "sha256=" + hmac.new(b"", BODY, hashlib.sha256).hexdigest()
    r = client.post("/webhook", content=BODY,
                    headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig})
    assert r.status_code == 403 and calls == []


def test_verify_signature_empty_secret_false():
    sig = "sha256=" + hmac.new(b"", BODY, hashlib.sha256).hexdigest()
    assert fb.verify_signature("", BODY, sig) is False


def test_parse_signed_request_empty_secret_none():
    payload = base64.urlsafe_b64encode(json.dumps({"user_id": "1"}).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(hmac.new(b"", payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    assert fb.parse_signed_request(f"{sig}.{payload}", "") is None
    # positive control: same construction with a real secret is accepted
    sig2 = base64.urlsafe_b64encode(hmac.new(b"k", payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    assert fb.parse_signed_request(f"{sig2}.{payload}", "k") == {"user_id": "1"}


def test_oauth_state_refuses_empty_secret(monkeypatch):
    _no_secret(monkeypatch, fb)
    with pytest.raises(RuntimeError):
        fb.sign_state({"ts": 1})
    # a state forged with an empty key must not verify
    import time
    raw = base64.urlsafe_b64encode(json.dumps({"ts": time.time()}).encode()).decode()
    forged = f"{raw}.{hmac.new(b'', raw.encode(), hashlib.sha256).hexdigest()}"
    assert fb.verify_state(forged) is None


def test_deletion_code_refuses_empty_secret_and_no_default_fallback(monkeypatch):
    # code forged with the old guessable "chatassist" fallback key
    raw = base64.urlsafe_b64encode(b"abc:1700000000").decode().rstrip("=")
    old = f"{raw}.{hmac.new(b'chatassist', raw.encode(), hashlib.sha256).hexdigest()[:16]}"
    _no_secret(monkeypatch, api_fb)
    with pytest.raises(RuntimeError):
        api_fb.make_deletion_code("42")
    assert api_fb.verify_deletion_code(old) is None


def test_data_deletion_routes_clean_failure_without_secret(client, monkeypatch):
    _no_secret(monkeypatch, api_fb)
    r = client.post("/facebook/data-deletion", data={"signed_request": "a.b"})
    assert r.status_code == 503 and "confirmation_code" not in r.text
    r = client.get("/facebook/data-deletion/status", params={"code": "x.y"})
    assert r.status_code == 200 and r.json()["valid"] is False


def test_webhook_get_verification_refuses_empty_verify_token(client, monkeypatch):
    monkeypatch.setattr(webhook, "get_settings", lambda: SimpleNamespace(fb_verify_token=""))
    r = client.get("/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "123"})
    assert r.status_code == 403


# ---- startup check ----
def test_missing_secrets_lists_exact_names():
    assert _prod().missing_required_secrets() == ALL_NAMES
    assert _prod(**_full(fb_app_secret="", gemini_api_key=" ")).missing_required_secrets() == [
        "GEMINI_API_KEY", "FB_APP_SECRET"]


def test_all_secrets_set_is_empty():
    assert _prod(**_full()).missing_required_secrets() == []


def test_invalid_fernet_key_reported_without_value():
    s = _prod(**_full(fb_token_encryption_key="not-a-fernet-key"))
    assert s.missing_required_secrets() == ["FB_TOKEN_ENCRYPTION_KEY (invalid format)"]
    assert "not-a-fernet-key" not in str(s.missing_required_secrets())


def test_startup_check_raises_in_production_with_names_only():
    with pytest.raises(RuntimeError) as e:
        check_required_settings(_prod(**_full(fb_app_secret="", fb_verify_token="")))
    msg = str(e.value)
    assert msg == "Missing required production settings: FB_APP_SECRET, FB_VERIFY_TOKEN"


def test_startup_check_passes_when_complete_and_in_development():
    check_required_settings(_prod(**_full()))
    check_required_settings(Settings(_env_file=None, app_env="development"))  # blank secrets OK
