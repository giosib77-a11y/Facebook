"""B-12 / S12-1: image download has a total deadline; bot fetches only own-Storage product photos."""
import contextlib

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


class _SlowResponse:
    """Streams one byte per 'tick'; each tick advances the fake clock by 5 s."""
    is_redirect = False
    headers = {"content-type": "image/jpeg"}

    def __init__(self, clock):
        self._clock = clock

    def raise_for_status(self):
        pass

    def iter_bytes(self):
        while True:
            self._clock["t"] += 5.0
            yield b"x"


def test_slow_drip_download_is_cut_by_total_deadline(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(fb.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(fb, "_is_public_http_url", lambda u: True)

    @contextlib.contextmanager
    def fake_stream(*a, **k):
        yield _SlowResponse(clock)

    monkeypatch.setattr(fb.httpx, "stream", fake_stream)
    assert fb.download_image("https://slow.example/a.jpg", max_bytes=10_000) is None
    # stopped around the 15 s deadline (3-4 ticks), not after 10_000 bytes
    assert clock["t"] - 1000.0 <= 25.0


def test_own_storage_url_tolerates_host_case_and_default_port(monkeypatch):
    monkeypatch.setattr(get_settings(), "supabase_url", "https://Proj.Supabase.co:443/")
    assert fb.is_own_storage_image_url(OWN)
