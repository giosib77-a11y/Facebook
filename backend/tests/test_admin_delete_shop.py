"""A-1: admin shop delete also cleans product-images/{shop_id}/*; sellers have no delete path."""
import pytest
from fastapi.testclient import TestClient

import app.api.admin
from app.api.admin import get_current_admin
from app.core.security import CurrentAuth
from app.main import app as fastapi_app
from tests.conftest import FakeSupabase

SHOP = "22222222-2222-2222-2222-222222222222"


class Bucket:
    def __init__(self, s):
        self.s = s

    def list(self, path=None, options=None):
        self.s.list_calls.append(path)
        if self.s.list_error:
            raise self.s.list_error
        return [{"name": n} for n in self.s.files[: (options or {}).get("limit", 100)]]

    def remove(self, paths):
        self.s.removed.append(list(paths))
        if self.s.remove_error:
            raise self.s.remove_error
        gone = {p.split("/", 1)[1] for p in paths}
        self.s.files = [f for f in self.s.files if f not in gone]


class Storage:
    def __init__(self, files):
        self.files = files
        self.list_calls, self.removed = [], []
        self.list_error = self.remove_error = None

    def from_(self, bucket):
        assert bucket == "product-images"
        return Bucket(self)


@pytest.fixture
def admin_db(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(app.api.admin, "get_service_client", lambda: db)
    fastapi_app.dependency_overrides[get_current_admin] = lambda: CurrentAuth(
        user_id="admin", email=None, client=db
    )
    try:
        yield db
    finally:
        fastapi_app.dependency_overrides.clear()


def test_admin_delete_removes_shop_folder_in_storage(admin_db):
    admin_db.responses[("shops", "select")] = [{"id": SHOP}]
    admin_db.storage = Storage([f"{i}.jpg" for i in range(150)])  # > one page
    r = TestClient(fastapi_app).delete(f"/admin/shops/{SHOP}")
    assert r.status_code == 204
    assert admin_db.storage.list_calls[0] == SHOP
    assert all(p.startswith(f"{SHOP}/") for batch in admin_db.storage.removed for p in batch)
    assert sum(len(b) for b in admin_db.storage.removed) == 150
    assert len(admin_db.calls_for("shops", "delete")) == 1


def test_storage_failure_does_not_block_delete(admin_db):
    admin_db.responses[("shops", "select")] = [{"id": SHOP}]
    admin_db.storage = Storage(["a.jpg"])
    admin_db.storage.remove_error = RuntimeError("storage down")
    r = TestClient(fastapi_app).delete(f"/admin/shops/{SHOP}")
    assert r.status_code == 204
    assert len(admin_db.calls_for("shops", "delete")) == 1


def test_storage_list_failure_does_not_block_delete(admin_db):
    admin_db.responses[("shops", "select")] = [{"id": SHOP}]
    admin_db.storage = Storage([])
    admin_db.storage.list_error = RuntimeError("storage down")
    assert TestClient(fastapi_app).delete(f"/admin/shops/{SHOP}").status_code == 204


def test_missing_shop_404_and_no_storage_touch(admin_db):
    admin_db.storage = Storage(["a.jpg"])
    r = TestClient(fastapi_app).delete(f"/admin/shops/{SHOP}")
    assert r.status_code == 404
    assert admin_db.storage.list_calls == [] and admin_db.storage.removed == []


def test_seller_cannot_use_admin_delete(client, user_db):
    r = client.delete(f"/admin/shops/{SHOP}")
    assert r.status_code == 403
    assert user_db.calls_for("shops", "delete") == []


def test_seller_has_no_shop_delete_route(client, user_db, service_db):
    r = client.delete(f"/shops/{SHOP}")
    assert r.status_code in (404, 405)
    assert user_db.calls_for("shops", "delete") == []
    assert service_db.calls_for("shops", "delete") == []
