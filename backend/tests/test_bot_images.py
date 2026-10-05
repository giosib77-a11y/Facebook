"""Product reference images stay within the per-message inline image budget (N-03).

download_image is faked — no network, no Gemini.
"""
import pytest

import app.services.facebook
from app.services import bot

MB = 1024 * 1024


@pytest.fixture
def fake_download(monkeypatch):
    """Serves `sizes[url]` bytes per URL and records every call's kwargs."""
    sizes: dict[str, int] = {}
    calls: list[tuple[str, dict]] = []

    def fake(url, **kwargs):
        calls.append((url, kwargs))
        return b"x" * sizes[url], "image/jpeg"

    monkeypatch.setattr(app.services.facebook, "download_image", fake)
    return sizes, calls


def _products(sizes, specs):
    """specs: [(name, size_bytes)] → product dicts with image_url; registers sizes."""
    products = []
    for name, size in specs:
        url = f"https://cdn.example.com/{name}.jpg"
        sizes[url] = size
        products.append({"name": name, "price": 10, "image_url": url})
    return products


def _total(refs):
    return sum(len(got[0]) for _, got in refs)


def test_refs_fill_budget_without_customer_images(fake_download):
    sizes, _ = fake_download
    products = _products(sizes, [(f"p{i}", 2 * MB) for i in range(12)])

    refs = bot._fetch_product_images(products, [])

    assert _total(refs) <= bot.INLINE_IMAGE_BUDGET
    assert len(refs) == 7


def test_refs_downloaded_with_per_ref_cap(fake_download):
    sizes, calls = fake_download
    products = _products(sizes, [("a", MB), ("b", MB)])

    bot._fetch_product_images(products, [])

    assert calls
    assert all(kw.get("max_bytes") == bot.PRODUCT_REF_MAX_BYTES for _, kw in calls)


def test_no_refs_when_customer_images_use_whole_budget(fake_download):
    sizes, calls = fake_download
    products = _products(sizes, [("a", MB), ("b", MB)])
    customer = [(b"x" * (10 * MB), "image/jpeg"), (b"x" * (5 * MB), "image/png")]

    refs = bot._fetch_product_images(products, customer)

    assert refs == []
    assert calls == []


def test_ref_over_remaining_budget_skipped_later_smaller_added(fake_download):
    sizes, _ = fake_download
    # 10 MB customer → 5 MB left: big1 (3) fits, big2 (3) would exceed, small (1) fits.
    products = _products(sizes, [("big1", 3 * MB), ("big2", 3 * MB), ("small", MB)])
    customer = [(b"x" * (10 * MB), "image/jpeg")]

    refs = bot._fetch_product_images(products, customer)

    names = [label.split(" — ")[0].removeprefix("• ") for label, _ in refs]
    assert names == ["big1", "small"]
    assert _total(refs) + 10 * MB <= bot.INLINE_IMAGE_BUDGET
