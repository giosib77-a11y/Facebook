"""FA-09: per-shop image quota, upload rate limit, orphaned image cleanup."""
import pytest

from app.core import ratelimit

SHOP = "22222222-2222-2222-2222-222222222222"
OTHER_SHOP = "33333333-3333-3333-3333-333333333333"
PRODUCT = "44444444-4444-4444-4444-444444444444"
PUBLIC = "https://proj.supabase.co/storage/v1/object/public/product-images"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
MB = 1024 * 1024


class FakeBucket:
    def __init__(self, storage, name):
        self._s, self.name = storage, name

    def list(self, path=None, options=None):
        self._s.list_calls.append((path, options))
        if self._s.list_error:
            raise self._s.list_error
        return self._s.objects

    def upload(self, path, content, options=None):
        self._s.uploads.append(path)

    def remove(self, paths):
        self._s.removed.append(list(paths))
        if self._s.remove_error:
            raise self._s.remove_error
        return []

    def get_public_url(self, path):
        # Mirrors storage3: no trailing slash for an empty path
        return f"https://proj.supabase.co/storage/v1/object/public/{self.name}" + (f"/{path}" if path else "")


class FakeStorage:
    def __init__(self):
        self.objects: list[dict] = []
        self.list_calls: list = []
        self.list_error: Exception | None = None
        self.uploads: list[str] = []
        self.removed: list[list[str]] = []
        self.remove_error: Exception | None = None

    def from_(self, bucket):
        return FakeBucket(self, bucket)


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    ratelimit._HITS.clear()
    yield
    ratelimit._HITS.clear()


@pytest.fixture
def storage(service_db):
    service_db.storage = FakeStorage()
    return service_db.storage


@pytest.fixture
def owned_shop(user_db):
    user_db.responses[("shops", "select")] = [{"id": SHOP}]


def _objects(n, size=1000):
    return [{"name": f"{i}.jpg", "metadata": {"size": size}} for i in range(n)]


def _upload(client, content=PNG):
    return client.post(
        "/products/upload-image",
        data={"shop_id": SHOP},
        files={"file": ("a.png", content, "image/png")},
    )


def _product_row(image_url):
    return {
        "id": PRODUCT, "shop_id": SHOP, "name": "x", "price": 1, "quantity": 1,
        "image_url": image_url, "is_active": True,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    }


# --- upload quota -----------------------------------------------------------

def test_count_quota_blocks_upload(client, storage, owned_shop):
    storage.objects = _objects(200)
    r = _upload(client)
    assert r.status_code == 400
    assert "ლიმიტი ამოწურულია" in r.json()["detail"]
    assert storage.uploads == []


def test_size_quota_blocks_upload(client, storage, owned_shop):
    storage.objects = [{"name": "big.jpg", "metadata": {"size": int(99.9 * MB)}}]
    r = _upload(client, PNG + b"\x00" * (MB - len(PNG)))
    assert r.status_code == 400
    assert storage.uploads == []


def test_list_failure_fails_closed(client, storage, owned_shop):
    storage.list_error = RuntimeError("storage down")
    r = _upload(client)
    assert r.status_code == 503
    assert storage.uploads == []


def test_under_quota_uploads(client, storage, owned_shop):
    storage.objects = _objects(3) + [{"name": "nometa.jpg", "metadata": None}]
    r = _upload(client)
    assert r.status_code == 200, r.text
    assert len(storage.uploads) == 1
    assert storage.uploads[0].startswith(f"{SHOP}/")
    assert storage.list_calls == [(SHOP, {"limit": 201})]
    assert r.json()["url"] == f"{PUBLIC}/{storage.uploads[0]}"


def test_upload_rate_limited(client, storage, owned_shop):
    for _ in range(5):
        assert _upload(client).status_code == 200
    r = _upload(client)
    assert r.status_code == 429
    assert len(storage.uploads) == 5


# --- delete_product cleanup -------------------------------------------------

def _delete(client, user_db, image_url):
    user_db.responses[("products", "select")] = [{"shop_id": SHOP, "image_url": image_url}]
    user_db.responses[("products", "delete")] = [{"id": PRODUCT}]
    return client.delete(f"/products/{PRODUCT}")


def test_delete_removes_own_image(client, user_db, storage):
    r = _delete(client, user_db, f"{PUBLIC}/{SHOP}/x.jpg")
    assert r.status_code == 204
    assert storage.removed == [[f"{SHOP}/x.jpg"]]


@pytest.mark.parametrize("url", [
    "https://cdn.example.com/x.jpg",
    f"{PUBLIC}/{OTHER_SHOP}/x.jpg",
    f"https://proj.supabase.co/storage/v1/object/public/other-bucket/{SHOP}/x.jpg",
    None,
])
def test_delete_leaves_foreign_images(client, user_db, storage, url):
    r = _delete(client, user_db, url)
    assert r.status_code == 204
    assert storage.removed == []


def test_delete_not_found_removes_nothing(client, user_db, storage):
    user_db.responses[("products", "select")] = [{"shop_id": SHOP, "image_url": f"{PUBLIC}/{SHOP}/x.jpg"}]
    r = client.delete(f"/products/{PRODUCT}")
    assert r.status_code == 404
    assert storage.removed == []


def test_delete_remove_failure_still_succeeds(client, user_db, storage):
    storage.remove_error = RuntimeError("storage down")
    r = _delete(client, user_db, f"{PUBLIC}/{SHOP}/x.jpg")
    assert r.status_code == 204
    assert storage.removed == [[f"{SHOP}/x.jpg"]]


# --- update_product cleanup -------------------------------------------------

def _update(client, user_db, old_url, payload):
    user_db.responses[("products", "select")] = [{"shop_id": SHOP, "image_url": old_url}]
    user_db.responses[("products", "update")] = [_product_row(payload.get("image_url", old_url))]
    return client.put(f"/products/{PRODUCT}", json=payload)


def test_update_new_image_removes_old(client, user_db, storage):
    r = _update(client, user_db, f"{PUBLIC}/{SHOP}/old.jpg", {"image_url": f"{PUBLIC}/{SHOP}/new.jpg"})
    assert r.status_code == 200, r.text
    assert storage.removed == [[f"{SHOP}/old.jpg"]]


def test_update_same_image_removes_nothing(client, user_db, storage):
    url = f"{PUBLIC}/{SHOP}/old.jpg"
    r = _update(client, user_db, url, {"image_url": url})
    assert r.status_code == 200
    assert storage.removed == []


def test_update_without_image_field_removes_nothing(client, user_db, storage):
    r = _update(client, user_db, f"{PUBLIC}/{SHOP}/old.jpg", {"name": "renamed"})
    assert r.status_code == 200
    assert storage.removed == []
    assert user_db.calls_for("products", "select") == []


def test_update_remove_failure_still_succeeds(client, user_db, storage):
    storage.remove_error = RuntimeError("storage down")
    r = _update(client, user_db, f"{PUBLIC}/{SHOP}/old.jpg", {"image_url": None})
    assert r.status_code == 200
    assert storage.removed == [[f"{SHOP}/old.jpg"]]
