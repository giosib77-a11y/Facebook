"""FA-03: in production, requests that bypass Cloudflare (no origin secret header) are rejected."""
import pytest

from app.config import get_settings

SECRET = "test-origin-secret"
HEADER = "x-origin-secret"


@pytest.fixture
def prod(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "origin_secret", SECRET)
    monkeypatch.setattr(settings, "origin_secret_header", HEADER)
    return settings


def test_o1_missing_header_rejected(client, prod):
    r = client.get("/status")
    assert r.status_code == 403 and r.json() == {"detail": "Forbidden"}


def test_o2_wrong_header_rejected(client, prod):
    r = client.get("/status", headers={HEADER: "wrong"})
    assert r.status_code == 403 and r.json() == {"detail": "Forbidden"}


def test_o3_correct_header_allowed(client, prod):
    r = client.get("/status", headers={HEADER: SECRET})
    assert r.status_code != 403
    assert r.status_code == 200


def test_o4_health_exempt(client, prod):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_o5_empty_secret_in_production_not_blocked(client, prod, monkeypatch):
    monkeypatch.setattr(prod, "origin_secret", "")
    r = client.get("/status")
    assert r.status_code == 200


def test_o6_not_production_not_blocked(client, prod, monkeypatch):
    monkeypatch.setattr(prod, "app_env", "development")
    r = client.get("/status")
    assert r.status_code == 200
