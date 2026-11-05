"""S21-5 (A-044 / N-12): Content-Security-Policy + remaining security headers; OAuth callback nonce."""
import re
from pathlib import Path
from types import SimpleNamespace

from app import main

STATIC_PART = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https:; "
)
TAIL_PART = (
    "; frame-ancestors 'self'; base-uri 'self'; form-action 'self'; object-src 'none'"
)
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _csp_for(url: str) -> str:
    return main.build_csp(SimpleNamespace(supabase_url=url))


def _directive(csp: str, name: str) -> str:
    for part in csp.split(";"):
        part = part.strip()
        if part.startswith(name + " "):
            return part
    raise AssertionError(f"{name} missing in {csp!r}")


def test_csp_header_on_every_response(client):
    expected = main.build_csp(main.settings)
    big = b"x" * (1024 * 1024 + 10)
    responses = [
        client.get("/status"),
        client.get("/panel/"),
        client.get("/no/such/path"),
        client.post("/webhook", content=big, headers={"Content-Type": "application/json"}),
    ]
    assert [r.status_code for r in responses][2:] == [404, 413]
    for r in responses:
        assert r.headers["Content-Security-Policy"] == expected, r.request.url
        assert "Content-Security-Policy-Report-Only" not in r.headers
    script_src = _directive(expected, "script-src")
    assert script_src == "script-src 'self'"
    assert "unsafe-inline" not in script_src and "unsafe-eval" not in script_src
    assert "unsafe-eval" not in expected


def test_build_csp_connect_src_variants():
    empty = _csp_for("")
    assert _csp_for("   ") == empty
    assert empty == STATIC_PART + "connect-src 'self'" + TAIL_PART
    assert "wss://" not in empty and "connect-src 'self';" in empty

    expected = (
        STATIC_PART
        + "connect-src 'self' https://abcd.supabase.co wss://abcd.supabase.co"
        + TAIL_PART
    )
    assert _csp_for("https://abcd.supabase.co") == expected
    assert _csp_for("https://abcd.supabase.co/") == expected
    assert _csp_for("https://abcd.supabase.co/rest/v1/") == expected
    # a value without a host never produces a broken source
    assert _csp_for("not-a-url") == empty


def test_report_only_switch(client, monkeypatch):
    expected = main.build_csp(main.settings)
    monkeypatch.setattr(main.settings, "csp_report_only", True)
    r = client.get("/status")
    assert r.headers["Content-Security-Policy-Report-Only"] == expected
    assert "Content-Security-Policy" not in r.headers
    monkeypatch.setattr(main.settings, "csp_report_only", False)
    r = client.get("/status")
    assert r.headers["Content-Security-Policy"] == expected
    assert "Content-Security-Policy-Report-Only" not in r.headers


def test_oauth_callback_uses_nonce_csp(client):
    def nonce_of(r):
        m = re.search(r'<script nonce="([A-Za-z0-9_-]+)">', r.text)
        assert m, r.text
        return m.group(1)

    r1 = client.get("/facebook/connect/callback", params={"error": "x"})
    r2 = client.get("/facebook/connect/callback", params={"error": "x"})
    n1, n2 = nonce_of(r1), nonce_of(r2)
    assert n1 != n2 and len(n1) >= 16
    for r, n in ((r1, n1), (r2, n2)):
        assert r.headers["Content-Security-Policy"] == (
            f"default-src 'none'; script-src 'nonce-{n}'; style-src 'unsafe-inline'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        # the middleware's setdefault must not add a second/overriding policy
        assert "Content-Security-Policy-Report-Only" not in r.headers
    # postMessage / redirect logic unchanged
    assert "window.opener.postMessage" in r1.text and "window.location.replace" in r1.text


def test_corp_and_cache_control(client):
    r = client.get("/status")
    assert r.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert r.headers["Cache-Control"] == "no-store"
    assert "Cross-Origin-Opener-Policy" not in r.headers  # FB popup window.opener

    assets = sorted((DIST / "assets").glob("*.js"))
    assert assets, "frontend/dist/assets missing"
    a = client.get(f"/panel/assets/{assets[0].name}")
    assert a.status_code == 200
    assert a.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert a.headers["Cross-Origin-Resource-Policy"] == "same-origin"

    h = client.get("/panel/")
    assert h.headers["Cache-Control"].startswith("no-store")


def test_existing_security_headers_unchanged(client):
    r = client.get("/status")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert r.headers["Permissions-Policy"] == "geolocation=(), microphone=(), camera=()"
