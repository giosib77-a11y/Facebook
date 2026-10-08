"""Rate limiter client-IP resolution: N-th X-Forwarded-For entry from the right; CF header ignored."""
import logging

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import get_settings
from app.core import ratelimit
from app.core.ratelimit import _client_ip, rate_limit


@pytest.fixture(autouse=True)
def isolated_limiter(monkeypatch):
    """Fresh hit store per test and known settings regardless of local .env."""
    ratelimit._HITS.clear()
    ratelimit._warned_missing_header[0] = False
    ratelimit._last_debug_log[0] = float("-inf")
    monkeypatch.setattr(get_settings(), "client_ip_trusted_hops", 1)
    monkeypatch.setattr(get_settings(), "client_ip_debug", False)
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


def test_r1_forged_cf_connecting_ip_is_ignored():
    req = _request({"CF-Connecting-IP": "6.6.6.6", "X-Forwarded-For": "203.0.113.7"})
    assert _client_ip(req) == "203.0.113.7"


def test_r2_cf_header_alone_falls_back_to_peer():
    req = _request({"CF-Connecting-IP": "6.6.6.6"}, peer="10.0.0.9")
    assert _client_ip(req) == "10.0.0.9"


def test_r3_forged_leftmost_xff_entries_ignored_with_one_hop():
    assert _client_ip(_request({"X-Forwarded-For": "evil, real"})) == "real"
    assert _client_ip(_request({"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 203.0.113.7"})) == "203.0.113.7"


def test_r4_two_hops_picks_second_from_right(monkeypatch):
    monkeypatch.setattr(get_settings(), "client_ip_trusted_hops", 2)
    req = _request({"X-Forwarded-For": "evil, 203.0.113.7, 10.1.1.1"})
    assert _client_ip(req) == "203.0.113.7"


def test_r5_too_few_entries_falls_back_to_peer(monkeypatch):
    monkeypatch.setattr(get_settings(), "client_ip_trusted_hops", 2)
    assert _client_ip(_request({"X-Forwarded-For": "203.0.113.7"}, peer="10.0.0.9")) == "10.0.0.9"
    assert _client_ip(_request({}, peer="10.0.0.9")) == "10.0.0.9"


def test_r6_malformed_xff_does_not_crash():
    assert _client_ip(_request({"X-Forwarded-For": " , ,"}, peer="10.0.0.9")) == "10.0.0.9"
    assert _client_ip(_request({"X-Forwarded-For": "a,,b ,"})) == "b"


def test_r7_invalid_hops_value_treated_as_one(monkeypatch):
    monkeypatch.setattr(get_settings(), "client_ip_trusted_hops", 0)
    assert _client_ip(_request({"X-Forwarded-For": "evil, real"})) == "real"


def test_r8_same_real_ip_with_forged_prefixes_shares_bucket():
    app = FastAPI()

    @app.get("/limited", dependencies=[Depends(rate_limit("test_r8", limit=2, window=60))])
    def limited():
        return {"ok": True}

    tc = TestClient(app)
    codes = [
        tc.get("/limited", headers={
            "CF-Connecting-IP": f"9.9.9.{i}",
            "X-Forwarded-For": f"6.6.6.{i}, 203.0.113.7",
        }).status_code
        for i in range(3)
    ]
    assert codes == [200, 200, 429]
    # a different real IP has its own bucket
    assert tc.get("/limited", headers={"X-Forwarded-For": "6.6.6.1, 198.51.100.2"}).status_code == 200


def test_r9_debug_logs_xff_and_choice_throttled(monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "client_ip_debug", True)
    req = _request({"X-Forwarded-For": "evil, real", "Authorization": "Bearer secret-token"})
    with caplog.at_level(logging.INFO, logger="app"):
        _client_ip(req)
        _client_ip(req)  # within 10s -> not logged again
    msgs = [r.getMessage() for r in caplog.records if "client-ip debug" in r.getMessage()]
    assert len(msgs) == 1
    assert "evil, real" in msgs[0] and "chosen=real" in msgs[0] and "peer=10.0.0.1" in msgs[0]
    assert "secret-token" not in msgs[0]


def test_r10_debug_off_logs_nothing(caplog):
    with caplog.at_level(logging.INFO, logger="app"):
        _client_ip(_request({"X-Forwarded-For": "evil, real"}))
    assert not [r for r in caplog.records if "client-ip debug" in r.getMessage()]


def test_r11_client_ip_endpoint_forbidden_for_seller(client):
    assert client.get("/admin/client-ip").status_code == 403
