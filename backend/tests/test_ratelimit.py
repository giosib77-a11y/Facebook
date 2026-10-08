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
    assert "evil, real" in msgs[0] and "resolved=real" in msgs[0] and "peer(untrusted)=10.0.0.1" in msgs[0]
    assert "secret-token" not in msgs[0]


def test_r12_production_too_few_entries_uses_shared_key_not_forged_peer(monkeypatch):
    # uvicorn proxy-headers would rewrite request.client.host from the client's XFF -> forged peer
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "client_ip_trusted_hops", 2)
    forged = _request({"X-Forwarded-For": "1.2.3.4"}, peer="1.2.3.4")
    other = _request({"X-Forwarded-For": "5.6.7.8"}, peer="5.6.7.8")
    assert _client_ip(forged) == "unknown"
    assert _client_ip(other) == "unknown"
    assert _client_ip(_request({}, peer="9.9.9.9")) == "unknown"


def test_r13_production_forged_peer_cannot_bypass_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "client_ip_trusted_hops", 2)
    app = FastAPI()

    @app.get("/limited", dependencies=[Depends(rate_limit("test_r13", limit=2, window=60))])
    def limited():
        return {"ok": True}

    tc = TestClient(app)
    codes = [tc.get("/limited", headers={"X-Forwarded-For": f"1.2.3.{i}"}).status_code for i in range(3)]
    assert codes == [200, 200, 429]


def test_r14_non_production_too_few_entries_uses_peer(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "development")
    monkeypatch.setattr(get_settings(), "client_ip_trusted_hops", 2)
    assert _client_ip(_request({"X-Forwarded-For": "1.2.3.4"}, peer="10.0.0.9")) == "10.0.0.9"


def test_r15_production_with_enough_entries_unaffected(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    assert _client_ip(_request({"X-Forwarded-For": "evil, 203.0.113.7"}, peer="1.1.1.1")) == "203.0.113.7"


def test_r16_debug_line_has_full_chain_and_resolved_ip(monkeypatch):
    """Capture via own handler on the `app` logger (works whatever propagate is)."""
    monkeypatch.setattr(get_settings(), "client_ip_debug", True)
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "client_ip_trusted_hops", 3)
    chain = ", ".join(f"10.0.{i}.1" for i in range(40))  # ~400 chars, > old 300 cap
    assert 300 < len(chain) < 1000
    records: list[str] = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    h = _H(level=logging.INFO)
    app_log = logging.getLogger("app")
    monkeypatch.setattr(app_log, "level", logging.INFO)
    app_log.addHandler(h)
    try:
        _client_ip(_request({"X-Forwarded-For": chain + "\nINJECTED"}, peer="7.7.7.7"))
    finally:
        app_log.removeHandler(h)
    lines = [m for m in records if "client-ip debug" in m]
    assert len(lines) == 1 and "\n" not in lines[0]  # %r keeps control chars escaped
    assert "10.0.0.1" in lines[0] and "10.0.39.1" in lines[0]  # first and last entry present
    assert "entries=40" in lines[0] and "hops=3" in lines[0] and "peer(untrusted)=7.7.7.7" in lines[0]
    assert "resolved=10.0.37.1" in lines[0]


def test_r17_debug_line_shows_shared_key_in_production_fallback(monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "client_ip_debug", True)
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "client_ip_trusted_hops", 2)
    with caplog.at_level(logging.INFO, logger="app"):
        _client_ip(_request({"X-Forwarded-For": "1.2.3.4"}, peer="1.2.3.4"))
    msg = [r.getMessage() for r in caplog.records if "client-ip debug" in r.getMessage()][0]
    assert "resolved=unknown" in msg and "'1.2.3.4'" in msg and "entries=1" in msg


def test_r18_debug_false_logs_nothing_via_handler(monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "client_ip_debug", False)
    with caplog.at_level(logging.DEBUG, logger="app"):
        _client_ip(_request({"X-Forwarded-For": "a, b"}))
    assert not [r for r in caplog.records if "client-ip" in r.getMessage()]


def test_r19_app_logger_has_stdout_handler_at_info_after_startup():
    """Regression for T22: `app` logger had no handler/level, so INFO was dropped in prod."""
    import sys

    import app.main  # noqa: F401  (startup configures logging)
    from app.core.logging import setup_logging

    app_log = logging.getLogger("app")
    handlers = [h for h in app_log.handlers if getattr(h, "_app_stdout_handler", False)]
    assert len(handlers) == 1
    assert app_log.level == logging.INFO and app_log.isEnabledFor(logging.INFO)
    # the handler targets stdout (sys.stdout may be swapped by pytest capture, so re-create it)
    app_log.removeHandler(handlers[0])
    setup_logging("INFO")
    assert [h.stream for h in app_log.handlers if getattr(h, "_app_stdout_handler", False)] == [sys.stdout]
    setup_logging("INFO")  # reload-safe: no duplicate handler
    assert len([h for h in app_log.handlers if getattr(h, "_app_stdout_handler", False)]) == 1
    setup_logging("bogus")  # invalid level -> INFO
    assert app_log.level == logging.INFO


def test_r10_debug_off_logs_nothing(caplog):
    with caplog.at_level(logging.INFO, logger="app"):
        _client_ip(_request({"X-Forwarded-For": "evil, real"}))
    assert not [r for r in caplog.records if "client-ip debug" in r.getMessage()]


def test_r11_client_ip_endpoint_forbidden_for_seller(client):
    assert client.get("/admin/client-ip").status_code == 403
