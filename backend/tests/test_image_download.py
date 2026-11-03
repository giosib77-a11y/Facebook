"""B-12 / S12-1: image download has a total deadline; bot fetches only own-Storage product photos."""
import logging
import socket

import httpx
import pytest

import app.services.facebook as fb
from app.config import get_settings
from app.services import bot

BASE = "https://proj.supabase.co"
OWN = f"{BASE}/storage/v1/object/public/product-images/shop1/a.jpg"


@pytest.fixture(autouse=True)
def _supabase_url(monkeypatch):
    monkeypatch.setattr(get_settings(), "supabase_url", BASE)


def test_own_storage_url_accepted_others_rejected():
    assert fb.is_own_storage_image_url(OWN)
    assert not fb.is_own_storage_image_url("https://evil.example/a.jpg")
    assert not fb.is_own_storage_image_url(f"{BASE}/storage/v1/object/public/other-bucket/a.jpg")
    assert not fb.is_own_storage_image_url(f"{BASE}.evil.com/storage/v1/object/public/product-images/a.jpg")
    assert not fb.is_own_storage_image_url(OWN.replace("shop1/", "../x/"))
    assert not fb.is_own_storage_image_url(None)


def test_own_storage_url_rejected_when_supabase_url_unset(monkeypatch):
    monkeypatch.setattr(get_settings(), "supabase_url", "")
    assert not fb.is_own_storage_image_url(OWN)


def test_bot_skips_external_image_urls(monkeypatch):
    calls = []
    monkeypatch.setattr(fb, "download_image", lambda url, **k: calls.append(url) or (b"x", "image/jpeg"))
    products = [
        {"name": "ext", "price": 1, "image_url": "https://evil.example/slow.jpg"},
        {"name": "own", "price": 1, "image_url": OWN},
    ]
    refs = bot._fetch_product_images(products, [])
    assert calls == [OWN]
    assert len(refs) == 1 and refs[0][0].startswith("• own")


class _SlowStream(httpx.SyncByteStream):
    """Streams one byte per 'tick'; each tick advances the fake clock by 5 s."""

    def __init__(self, clock):
        self._clock = clock

    def __iter__(self):
        while True:
            self._clock["t"] += 5.0
            yield b"x"


def test_slow_drip_download_is_cut_by_total_deadline(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(fb.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(fb, "_resolve_public", lambda u: (httpx.URL(u), "93.184.216.34"))
    monkeypatch.setattr(
        fb, "_TRANSPORT",
        httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "image/jpeg"}, stream=_SlowStream(clock))
        ),
    )
    assert fb.download_image("https://slow.example/a.jpg", max_bytes=10_000) is None
    # stopped around the 15 s deadline (3-4 ticks), not after 10_000 bytes
    assert clock["t"] - 1000.0 <= 25.0


def test_own_storage_url_tolerates_host_case_and_default_port(monkeypatch):
    monkeypatch.setattr(get_settings(), "supabase_url", "https://Proj.Supabase.co:443/")
    assert fb.is_own_storage_image_url(OWN)


# ---- A-028 (N-17): non-image -> None; connect to the already-checked IP ----
PUBLIC_IP = "93.184.216.34"
CDN = "https://cdn.example.com/a.png"


def _dns(monkeypatch, table):
    """Fake getaddrinfo: table[host] is a list of answers, one per call (the last one repeats)."""
    calls = []

    def fake(host, port, *a, **k):
        calls.append(host)
        answers = table[host]
        ip = answers[min(sum(1 for h in calls if h == host) - 1, len(answers) - 1)]
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(fb.socket, "getaddrinfo", fake)
    return calls


def _transport(monkeypatch, handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(fb, "_TRANSPORT", httpx.MockTransport(wrapped))
    return seen


def _ok(content_type="image/png", body=b"IMG"):
    headers = {"content-type": content_type} if content_type else {}
    return lambda request: httpx.Response(200, headers=headers, content=body)


@pytest.mark.parametrize("ctype", ["text/html", "text/html; charset=utf-8", "application/json", None])
def test_non_image_content_type_returns_none(monkeypatch, caplog, ctype):
    _dns(monkeypatch, {"cdn.example.com": [PUBLIC_IP]})
    _transport(monkeypatch, _ok(ctype, b"<html>not an image</html>"))
    with caplog.at_level(logging.WARNING, logger="app"):
        assert fb.download_image(CDN) is None
    assert "image download: not an image" in caplog.text


def test_image_content_type_with_params_is_returned_normalized(monkeypatch):
    _dns(monkeypatch, {"cdn.example.com": [PUBLIC_IP]})
    _transport(monkeypatch, _ok("Image/PNG; charset=x"))
    assert fb.download_image(CDN) == (b"IMG", "image/png")


def test_connects_to_checked_ip_with_original_host_and_sni_one_resolve(monkeypatch):
    # DNS rebinding: 1st answer public, any later answer loopback
    dns_calls = _dns(monkeypatch, {"cdn.example.com": [PUBLIC_IP, "127.0.0.1"]})
    seen = _transport(monkeypatch, _ok())
    assert fb.download_image(CDN) == (b"IMG", "image/png")
    assert dns_calls == ["cdn.example.com"]  # one resolution per hop
    (req,) = seen
    assert req.url.host == PUBLIC_IP
    assert req.url.scheme == "https" and req.url.path == "/a.png"
    assert req.headers["host"] == "cdn.example.com"
    assert req.extensions["sni_hostname"] == "cdn.example.com"


def test_non_default_port_is_kept_in_url_and_host_header(monkeypatch):
    _dns(monkeypatch, {"cdn.example.com": [PUBLIC_IP]})
    seen = _transport(monkeypatch, _ok())
    assert fb.download_image("https://cdn.example.com:8443/a.png?x=1") == (b"IMG", "image/png")
    (req,) = seen
    assert req.url.host == PUBLIC_IP and req.url.port == 8443 and req.url.query == b"x=1"
    assert req.headers["host"] == "cdn.example.com:8443"


def test_public_ipv6_goes_in_brackets(monkeypatch):
    v6 = "2606:4700::6810:84e5"
    _dns(monkeypatch, {"cdn.example.com": [v6]})
    seen = _transport(monkeypatch, _ok())
    assert fb.download_image(CDN) == (b"IMG", "image/png")
    (req,) = seen
    assert req.url.host == v6
    assert f"[{v6}]" in str(req.url)
    assert req.headers["host"] == "cdn.example.com"


def test_ipv4_preferred_over_earlier_ipv6_when_both_public(monkeypatch):
    v6 = "2606:4700::6810:84e5"
    monkeypatch.setattr(fb.socket, "getaddrinfo", lambda host, port, *a, **k: [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (v6, 0, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 0)),
    ])
    seen = _transport(monkeypatch, _ok())
    assert fb.download_image(CDN) == (b"IMG", "image/png")
    assert seen[0].url.host == PUBLIC_IP
    assert fb._resolve_public(CDN)[1] == PUBLIC_IP


def test_private_address_among_public_ones_still_blocks(monkeypatch):
    monkeypatch.setattr(fb.socket, "getaddrinfo", lambda host, port, *a, **k: [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700::6810:84e5", 0, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0)),
    ])
    assert fb._resolve_public(CDN) is None


def test_redirect_to_other_host_is_resolved_and_pinned_again(monkeypatch):
    dns_calls = _dns(monkeypatch, {"cdn.example.com": [PUBLIC_IP], "other.example.org": ["93.184.216.35"]})

    def handler(request):
        if request.headers["host"] == "cdn.example.com":
            return httpx.Response(302, headers={"location": "https://other.example.org/b.png"})
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"B")

    seen = _transport(monkeypatch, handler)
    assert fb.download_image(CDN) == (b"B", "image/png")
    assert dns_calls == ["cdn.example.com", "other.example.org"]
    assert [r.url.host for r in seen] == [PUBLIC_IP, "93.184.216.35"]
    assert seen[1].headers["host"] == "other.example.org"
    assert seen[1].extensions["sni_hostname"] == "other.example.org"


def test_relative_redirect_is_joined_against_original_hostname(monkeypatch):
    dns_calls = _dns(monkeypatch, {"cdn.example.com": [PUBLIC_IP]})

    def handler(request):
        if request.url.path == "/a.png":
            return httpx.Response(301, headers={"location": "/b.png"})
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"B")

    seen = _transport(monkeypatch, handler)
    assert fb.download_image(CDN) == (b"B", "image/png")
    assert dns_calls == ["cdn.example.com", "cdn.example.com"]
    assert seen[1].headers["host"] == "cdn.example.com" and seen[1].url.path == "/b.png"


@pytest.mark.parametrize("location,answers", [
    ("http://internal.example/x", {"internal.example": ["10.0.0.5"]}),
    ("http://169.254.169.254/latest/meta-data", {"169.254.169.254": ["169.254.169.254"]}),
])
def test_redirect_to_internal_address_is_blocked(monkeypatch, caplog, location, answers):
    _dns(monkeypatch, {"cdn.example.com": [PUBLIC_IP], **answers})
    seen = _transport(monkeypatch, lambda request: httpx.Response(302, headers={"location": location}))
    with caplog.at_level(logging.WARNING, logger="app"):
        assert fb.download_image(CDN) is None
    assert len(seen) == 1  # the internal hop never got a request
    assert "არასაჯარო მისამართი" in caplog.text


def test_private_first_address_never_sends_a_request(monkeypatch):
    _dns(monkeypatch, {"cdn.example.com": ["127.0.0.1"]})
    seen = _transport(monkeypatch, _ok())
    assert fb.download_image(CDN) is None
    assert seen == []


def test_env_proxy_is_ignored(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    _dns(monkeypatch, {"cdn.example.com": [PUBLIC_IP]})
    seen = _transport(monkeypatch, _ok())
    assert fb.download_image(CDN) == (b"IMG", "image/png")
    assert len(seen) == 1  # served by our transport, not routed to the env proxy


def test_resolve_public_returns_parsed_url_and_first_ip(monkeypatch):
    _dns(monkeypatch, {"cdn.example.com": [PUBLIC_IP]})
    url, ip = fb._resolve_public("https://cdn.example.com/a.png")
    assert url.host == "cdn.example.com" and ip == PUBLIC_IP
    assert fb._is_public_http_url("https://cdn.example.com/a.png") is True
    assert fb._resolve_public("ftp://cdn.example.com/a.png") is None
    assert fb._is_public_http_url("file:///etc/passwd") is False
