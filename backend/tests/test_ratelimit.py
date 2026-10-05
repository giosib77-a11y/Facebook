"""Rate limiter client-IP resolution: proxy header wins, X-Forwarded-For is never trusted."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import get_settings
from app.core import ratelimit
from app.core.ratelimit import _client_ip, rate_limit


@pytest.fixture(autouse=True)
def isolated_limiter(monkeypatch):
    """Fresh hit store per test and a known header name regardless of local .env."""
    ratelimit._HITS.clear()
    monkeypatch.setattr(get_settings(), "client_ip_header", "cf-connecting-ip")
    yield
    ratelimit._HITS.clear()


def _request(headers: dict[str, str], peer: str = "10.0.0.1") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 12345),
    })


def test_r1_configured_header_beats_spoofed_xff():
    req = _request({"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "6.6.6.6, 203.0.113.7"})
    assert _client_ip(req) == "203.0.113.7"


def test_r2_header_absent_uses_peer_not_xff():
    req = _request({"X-Forwarded-For": "6.6.6.6"}, peer="10.0.0.9")
    assert _client_ip(req) == "10.0.0.9"


def test_r3_rotating_xff_does_not_bypass_limit():
    app = FastAPI()

    @app.get("/limited", dependencies=[Depends(rate_limit("test_r3", limit=2, window=60))])
    def limited():
        return {"ok": True}

    tc = TestClient(app)
    codes = [
        tc.get("/limited", headers={"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": f"6.6.6.{i}"}).status_code
        for i in range(3)
    ]
    assert codes == [200, 200, 429]


def test_r4_client_ip_endpoint_forbidden_for_seller(client):
    assert client.get("/admin/client-ip").status_code == 403
