"""B-5: POST /webhook verifies X-Hub-Signature-256 (HMAC-SHA256 of the raw body)."""
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

import app.api.webhook as webhook

SECRET = "test-app-secret"
BODY = json.dumps({"object": "page", "entry": [{"id": "123", "messaging": []}]}).encode()


def _sig(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def processed(monkeypatch):
    """Fixed app secret; background processing is replaced so nothing external runs."""
    monkeypatch.setattr(webhook, "get_settings", lambda: SimpleNamespace(fb_app_secret=SECRET))
    calls = []
    monkeypatch.setattr(webhook, "_process_events", lambda data: calls.append(data))
    return calls


def _post(client, body, signature):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    return client.post("/webhook", content=body, headers=headers)


def test_valid_signature_accepted(client, processed):
    r = _post(client, BODY, _sig(BODY))
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert len(processed) == 1


def test_wrong_signature_rejected(client, processed):
    r = _post(client, BODY, _sig(BODY, secret="other-secret"))
    assert r.status_code == 403
    assert processed == []


def test_missing_header_rejected(client, processed):
    r = _post(client, BODY, None)
    assert r.status_code == 403
    assert processed == []


@pytest.mark.parametrize(
    "header",
    [
        hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest(),  # no "sha256=" prefix
        "sha1=" + hmac.new(SECRET.encode(), BODY, hashlib.sha1).hexdigest(),
        "sha256=",
        "garbage",
        "sha256=zzzz-not-hex",
        "",
    ],
)
def test_malformed_header_rejected(client, processed, header):
    r = _post(client, BODY, header)
    assert r.status_code == 403
    assert processed == []


def test_tampered_body_with_old_signature_rejected(client, processed):
    old_sig = _sig(BODY)
    tampered = BODY.replace(b'"123"', b'"999"')
    assert tampered != BODY
    r = _post(client, tampered, old_sig)
    assert r.status_code == 403
    assert processed == []
