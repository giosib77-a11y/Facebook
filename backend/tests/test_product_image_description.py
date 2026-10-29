"""S18-4: create_product / update_product write a text description of the product photo
(products.image_description), clear it when the photo goes away, 30 per hour per shop.

Offline: fake Claude client, fake user/service Supabase (conftest), monkeypatched download - no network,
no .env. The description is never part of an API response."""
import asyncio
import logging
import uuid
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from postgrest.exceptions import APIError

from app.api import products
from app.core import ratelimit
from app.core.security import CurrentAuth
from app.models.product import ProductCreate, ProductUpdate
from app.services import facebook, llm, vision
from conftest import USER_ID, FakeQuery, FakeResult

SHOP = "22222222-2222-2222-2222-222222222222"
OTHER_SHOP = "33333333-3333-3333-3333-333333333333"
PRODUCT = "44444444-4444-4444-4444-444444444444"
PUBLIC = "https://proj.supabase.co/storage/v1/object/public/product-images"
OWN_URL = f"{PUBLIC}/{SHOP}/new.png"
OLD_URL = f"{PUBLIC}/{SHOP}/old.png"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(60))
DESC = "EN: A red cotton t-shirt with a white logo.\nKA: მაისური, წითელი, ბამბა"


def _claude_response(text=DESC):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )


class FakeBucket:
    def __init__(self, storage, name):
        self._s, self.name = storage, name

    def get_public_url(self, path):
        if self._s.error:
            raise self._s.error
        return f"https://proj.supabase.co/storage/v1/object/public/{self.name}" + (f"/{path}" if path else "")

    def remove(self, paths):
        self._s.removed.append(list(paths))
        return []


class FakeStorage:
    def __init__(self):
        self.removed: list[list[str]] = []
        self.error: Exception | None = None

    def from_(self, bucket):
        return FakeBucket(self, bucket)


class World:
    """Fake Claude client + fake storage + download stub on top of conftest's two fake databases."""

    def __init__(self, monkeypatch, user_db, service_db):
        self.user_db, self.db = user_db, service_db
        self.requests: list[dict] = []
        self.script: list = []  # a response or an Exception; empty -> the default description
        self.downloads: list[str] = []
        self.factory_calls = 0
        self.on_call = None  # hook run inside the LLM call (simulates something happening meanwhile)
        self.inserts_at_call: list[int] = []  # product inserts already done when the LLM was called
        self.settings = llm.get_settings()
        service_db.storage = FakeStorage()
        monkeypatch.setattr(llm, "get_settings", lambda: self.settings)
        monkeypatch.setattr(llm, "get_service_client", lambda: service_db)

        def create(**kwargs):
            self.requests.append(kwargs)
            self.inserts_at_call.append(len(service_db.calls_for("products", "insert")))
            if self.on_call:
                self.on_call()
            item = self.script.pop(0) if self.script else _claude_response()
            if isinstance(item, Exception):
                raise item
            return item

        def factory(s):
            self.factory_calls += 1
            return SimpleNamespace(messages=SimpleNamespace(create=create))

        monkeypatch.setattr(llm, "_anthropic_client", factory)
        monkeypatch.setattr(facebook, "is_own_storage_image_url", lambda url: bool(url) and url.startswith(PUBLIC + "/"))

        def download(url, max_bytes=None, timeout=None):
            self.downloads.append(url)
            return PNG, "image/png"

        monkeypatch.setattr(facebook, "download_image", download)

    @property
    def desc_updates(self):
        return self.db.calls_for("products", "update")

    @property
    def usage_rows(self):
        return self.db.calls_for("llm_usage", "insert")


@pytest.fixture
def world(monkeypatch, user_db, service_db):
    return World(monkeypatch, user_db, service_db)


@pytest.fixture(autouse=True)
def _column_present(monkeypatch):
    monkeypatch.setattr(vision, "_column_missing", False)


def _row(image_url, shop=SHOP):
    return {
        "id": PRODUCT, "shop_id": shop, "name": "x", "price": 1, "quantity": 1,
        "image_url": image_url, "is_active": True, "image_description": "OLD DESCRIPTION",
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    }


def _create(client, world, image_url, shop=SHOP):
    world.user_db.responses[("shops", "select")] = [{"id": shop}]
    world.db.responses[("products", "insert")] = [_row(image_url, shop)]
    payload = {"shop_id": shop, "name": "x", "price": 1, "quantity": 1}
    if image_url is not None:
        payload["image_url"] = image_url
    return client.post("/products", json=payload)


def _update(client, world, old_url, payload, shop=SHOP):
    world.user_db.responses[("products", "select")] = [{"shop_id": shop, "image_url": old_url}]
    world.user_db.responses[("products", "update")] = [_row(payload.get("image_url", old_url), shop)]
    return client.put(f"/products/{PRODUCT}", json=payload)


def _warnings(caplog, needle):
    return [r for r in caplog.records if r.levelno == logging.WARNING and needle in r.getMessage()]


def _log_text(caplog):
    return "\n".join(r.getMessage() + " " + str(r.exc_text or "") + " " + repr(r.args) for r in caplog.records)


def _filters(call):
    return call.filters


# ---------------------------------------------------------------------------
# create_product
# ---------------------------------------------------------------------------
def test_create_with_own_photo_describes_and_saves(client, world):
    r = _create(client, world, OWN_URL)
    assert r.status_code == 201, r.text
    # the insert payload is unchanged: no image_description key
    inserts = world.db.calls_for("products", "insert")
    assert len(inserts) == 1
    assert "image_description" not in inserts[0].payload
    assert inserts[0].payload["image_url"] == OWN_URL
    # one conditional update with the description
    assert len(world.desc_updates) == 1
    upd = world.desc_updates[0]
    assert upd.payload == {"image_description": DESC}
    assert _filters(upd) == [("eq", "id", PRODUCT), ("eq", "shop_id", SHOP), ("eq", "image_url", OWN_URL)]
    # it happens after the insert, on the service client only
    assert world.db.calls.index(inserts[0]) < world.db.calls.index(upd)
    assert world.user_db.calls_for("products", "update") == []
    # one LLM call with the photo, one usage row
    assert world.downloads == [OWN_URL]
    assert len(world.requests) == 1
    content = world.requests[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[-1]["type"] == "text"
    assert len(world.usage_rows) == 1
    assert world.usage_rows[0].payload["shop_id"] == SHOP
    # the API response does not expose the description (even when the row carries one)
    assert "image_description" not in r.json()
    assert r.json()["image_url"] == OWN_URL


@pytest.mark.parametrize("url", [
    None,
    "https://cdn.example.com/x.jpg",
    f"{PUBLIC}/{OTHER_SHOP}/x.jpg",
    f"https://proj.supabase.co/storage/v1/object/public/other-bucket/{SHOP}/x.jpg",
])
def test_create_without_own_photo_makes_no_llm_call_and_no_update(client, world, url):
    r = _create(client, world, url)
    assert r.status_code == 201, r.text
    assert world.requests == [] and world.downloads == []
    assert world.desc_updates == []


# ---------------------------------------------------------------------------
# update_product
# ---------------------------------------------------------------------------
def test_update_to_a_new_own_photo_saves_a_description_for_that_url(client, world):
    r = _update(client, world, OLD_URL, {"image_url": OWN_URL})
    assert r.status_code == 200, r.text
    # the old photo's description is cleared at once (it does not describe the new photo), then the new
    # one is written by the background task; both only while the row still has the new photo
    assert [u.payload for u in world.desc_updates] == [{"image_description": None}, {"image_description": DESC}]
    for upd in world.desc_updates:
        assert _filters(upd) == [("eq", "id", PRODUCT), ("eq", "shop_id", SHOP), ("eq", "image_url", OWN_URL)]
    assert len(world.requests) == 1
    assert "image_description" not in r.json()
    # the old photo is still removed from Storage (existing behaviour)
    assert world.db.storage.removed == [[f"{SHOP}/old.png"]]


def test_update_with_the_same_photo_does_nothing(client, world):
    r = _update(client, world, OWN_URL, {"image_url": OWN_URL})
    assert r.status_code == 200
    assert world.requests == [] and world.desc_updates == []


def test_update_removing_the_photo_clears_the_description_without_llm(client, world):
    r = _update(client, world, OLD_URL, {"image_url": None})
    assert r.status_code == 200, r.text
    assert world.requests == [] and world.downloads == []
    assert len(world.desc_updates) == 1
    upd = world.desc_updates[0]
    assert upd.payload == {"image_description": None}
    assert _filters(upd) == [("eq", "id", PRODUCT), ("eq", "shop_id", SHOP)]


@pytest.mark.parametrize("url", [
    "https://cdn.example.com/x.jpg",
    f"{PUBLIC}/{OTHER_SHOP}/x.jpg",
])
def test_update_to_a_foreign_photo_clears_the_description_without_llm(client, world, url):
    r = _update(client, world, OLD_URL, {"image_url": url})
    assert r.status_code == 200, r.text
    assert world.requests == [] and world.downloads == []
    assert [u.payload for u in world.desc_updates] == [{"image_description": None}]
    assert _filters(world.desc_updates[0])[-1] == ("eq", "image_url", url)


def test_update_of_another_field_leaves_the_description_alone(client, world):
    r = _update(client, world, OLD_URL, {"price": 5})
    assert r.status_code == 200, r.text
    assert world.requests == [] and world.desc_updates == []
    assert world.user_db.calls_for("products", "select") == []


def test_delete_makes_no_description(client, world):
    world.user_db.responses[("products", "select")] = [{"shop_id": SHOP, "image_url": OLD_URL}]
    world.user_db.responses[("products", "delete")] = [{"id": PRODUCT}]
    assert client.delete(f"/products/{PRODUCT}").status_code == 204
    assert world.requests == [] and world.desc_updates == []


# ---------------------------------------------------------------------------
# failures never fail the save
# ---------------------------------------------------------------------------
def _fail_llm(world, kind):
    if kind == "exception":
        world.script = [RuntimeError("boom " + DESC)]
    elif kind == "timeout":
        world.script = [TimeoutError("budget")]
    elif kind == "empty":
        world.script = [_claude_response("  ")]
    elif kind == "no_key":
        world.settings = world.settings.model_copy(update={"anthropic_api_key": ""})


@pytest.mark.parametrize("kind", ["exception", "timeout", "empty", "no_key"])
def test_description_failure_keeps_create_201_and_writes_nothing(client, world, caplog, kind):
    _fail_llm(world, kind)
    with caplog.at_level(logging.WARNING):
        r = _create(client, world, OWN_URL)
    assert r.status_code == 201, r.text
    assert world.desc_updates == []
    assert _warnings(caplog, "image description failed")
    text = _log_text(caplog)
    assert "მაისური" not in text and OWN_URL not in text


@pytest.mark.parametrize("kind", ["exception", "timeout", "empty", "no_key"])
def test_description_failure_on_update_clears_the_old_description(client, world, caplog, kind):
    _fail_llm(world, kind)
    with caplog.at_level(logging.WARNING):
        r = _update(client, world, OLD_URL, {"image_url": OWN_URL})
    assert r.status_code == 200, r.text
    assert [u.payload for u in world.desc_updates] == [{"image_description": None}]
    assert _filters(world.desc_updates[0])[-1] == ("eq", "image_url", OWN_URL)
    assert _warnings(caplog, "image description failed")
    text = _log_text(caplog)
    assert "მაისური" not in text and OWN_URL not in text


def test_failed_save_does_not_fail_the_request(client, world, caplog):
    world.db.errors[("products", "update")] = RuntimeError("db down")
    with caplog.at_level(logging.WARNING):
        r = _create(client, world, OWN_URL)
    assert r.status_code == 201, r.text
    assert _warnings(caplog, "image description save failed")


def test_storage_error_while_checking_the_photo_path_never_fails_the_request(client, world, caplog):
    # _own_image_path -> get_service_client().storage... raises; the product is already saved
    world.db.storage.error = RuntimeError("storage down")
    with caplog.at_level(logging.WARNING):
        r = _create(client, world, OWN_URL)
    assert r.status_code == 201, r.text
    assert world.requests == [] and world.desc_updates == []
    assert _warnings(caplog, "image description failed")


def test_describe_raising_unexpectedly_is_contained(client, world, monkeypatch, caplog):
    def boom(shop_id, url):
        raise ValueError("unexpected " + DESC)

    monkeypatch.setattr(vision, "describe_product_image", boom)
    with caplog.at_level(logging.WARNING):
        r = _create(client, world, OWN_URL)
    assert r.status_code == 201, r.text
    assert "ValueError" in _warnings(caplog, "image description failed")[0].getMessage()
    assert "მაისური" not in _log_text(caplog)


# ---------------------------------------------------------------------------
# the description is a background task: the save returns first
# ---------------------------------------------------------------------------
def _auth(world):
    return CurrentAuth(user_id=USER_ID, email="s@t.local", client=world.user_db)


def _direct_create(world, tasks, image_url=OWN_URL):
    world.user_db.responses[("shops", "select")] = [{"id": SHOP}]
    world.db.responses[("products", "insert")] = [_row(image_url)]
    payload = ProductCreate(shop_id=SHOP, name="x", price=1, quantity=1, image_url=image_url)
    return products.create_product(payload, tasks, _auth(world))


def test_create_handler_returns_before_any_download_or_llm_call(world):
    """Called directly: when the handler returns, no photo was fetched and the LLM did not run;
    the description is a queued task that runs after the response."""
    tasks = BackgroundTasks()
    out = _direct_create(world, tasks)
    assert out["id"] == PRODUCT
    assert world.downloads == [] and world.requests == [] and world.desc_updates == []
    assert len(tasks.tasks) == 1
    asyncio.run(tasks())
    assert world.downloads == [OWN_URL] and len(world.requests) == 1
    assert [u.payload for u in world.desc_updates] == [{"image_description": DESC}]


def test_update_handler_clears_now_and_queues_the_description(world):
    world.user_db.responses[("products", "select")] = [{"shop_id": SHOP, "image_url": OLD_URL}]
    world.user_db.responses[("products", "update")] = [_row(OWN_URL)]
    tasks = BackgroundTasks()
    products.update_product(uuid.UUID(PRODUCT), ProductUpdate(image_url=OWN_URL), tasks, _auth(world))
    assert world.requests == [] and world.downloads == []
    assert [u.payload for u in world.desc_updates] == [{"image_description": None}]  # old text gone at once
    assert len(tasks.tasks) == 1
    asyncio.run(tasks())
    assert [u.payload for u in world.desc_updates] == [{"image_description": None}, {"image_description": DESC}]


def test_llm_runs_only_after_the_product_is_inserted(client, world):
    assert _create(client, world, OWN_URL).status_code == 201
    assert world.inserts_at_call == [1]


@pytest.mark.parametrize("url", [None, "https://cdn.example.com/x.jpg", f"{PUBLIC}/{OTHER_SHOP}/x.jpg"])
def test_no_background_task_for_a_missing_or_foreign_photo(world, url):
    tasks = BackgroundTasks()
    _direct_create(world, tasks, url)
    assert tasks.tasks == []


def test_no_background_task_when_the_hourly_limit_is_hit(world, caplog):
    for _ in range(products.IMAGE_DESCRIBE_PER_HOUR):
        assert ratelimit.allow("image_describe", SHOP, products.IMAGE_DESCRIBE_PER_HOUR, 3600)
    tasks = BackgroundTasks()
    with caplog.at_level(logging.WARNING):
        out = _direct_create(world, tasks)
    assert out["id"] == PRODUCT  # the product is saved regardless
    assert tasks.tasks == []  # nothing scheduled, so nothing runs later
    assert len(_warnings(caplog, "image description skipped: hourly limit")) == 1
    # the next shop is unaffected
    assert ratelimit.allow("image_describe", OTHER_SHOP, products.IMAGE_DESCRIBE_PER_HOUR, 3600)


def test_the_limit_is_counted_when_scheduling_not_when_running(world):
    tasks = BackgroundTasks()
    _direct_create(world, tasks)
    assert len(ratelimit._HITS["image_describe"][SHOP]) == 1  # counted before the background task ran


class StatefulProducts(FakeQuery):
    """products updates are applied to one in-memory row, honouring the eq filters like Postgres would."""

    def execute(self):
        if self.table == "products" and self.op == "update":
            self._db.calls.append(self)
            row = self._db.row
            if all(row.get(c) == v for kind, c, v in self.filters if kind == "eq"):
                row.update(self.payload)
                return FakeResult([dict(row)])
            return FakeResult([])
        return super().execute()


@pytest.fixture
def row_db(world):
    world.db.row = {"id": PRODUCT, "shop_id": SHOP, "image_url": OWN_URL, "image_description": None}
    world.db.table = lambda name: StatefulProducts(world.db, name)
    return world.db


def test_background_description_lands_when_the_photo_is_unchanged(client, world, row_db):
    assert _create(client, world, OWN_URL).status_code == 201
    assert row_db.row["image_description"] == DESC


def test_photo_changed_during_the_background_run_gets_no_stale_description(client, world, row_db, caplog):
    world.on_call = lambda: row_db.row.update(image_url=f"{PUBLIC}/{SHOP}/newer.png")
    with caplog.at_level(logging.WARNING):
        assert _create(client, world, OWN_URL).status_code == 201
    assert len(world.requests) == 1  # the description of the first photo was generated ...
    assert row_db.row["image_description"] is None  # ... but not written onto the row of the newer photo
    assert world.desc_updates[-1].payload == {"image_description": DESC}
    assert ("eq", "image_url", OWN_URL) in _filters(world.desc_updates[-1])


def test_product_gone_during_the_background_run_writes_nothing(client, world, row_db):
    world.on_call = lambda: row_db.row.update(id="55555555-5555-5555-5555-555555555555")
    assert _create(client, world, OWN_URL).status_code == 201
    assert row_db.row["image_description"] is None


# ---------------------------------------------------------------------------
# migration 0028 not applied
# ---------------------------------------------------------------------------
def _missing_column_error():
    return APIError({"message": "Could not find the 'image_description' column of 'products' in the schema cache",
                     "code": "PGRST204", "hint": None, "details": None})


def test_missing_column_warns_once_and_stops_calling_the_llm(client, world, caplog):
    world.db.errors[("products", "update")] = _missing_column_error()
    with caplog.at_level(logging.WARNING):
        r1 = _create(client, world, OWN_URL)
        assert len(world.requests) == 1
        r2 = _create(client, world, OWN_URL)
        r3 = _update(client, world, OLD_URL, {"image_url": OWN_URL})
    assert (r1.status_code, r2.status_code, r3.status_code) == (201, 201, 200)
    assert len(_warnings(caplog, "products.image_description missing")) == 1
    assert len(world.requests) == 1  # the second and third requests never reached the LLM
    assert len(world.desc_updates) == 1  # ... nor even tried another update
    assert vision.descriptions_enabled() is False


# ---------------------------------------------------------------------------
# 30 per hour per shop
# ---------------------------------------------------------------------------
def test_31st_description_in_an_hour_is_skipped_but_the_product_is_saved(client, world, caplog):
    from app.api import products

    assert products.IMAGE_DESCRIBE_PER_HOUR == 30
    for _ in range(30):
        assert _create(client, world, OWN_URL).status_code == 201
    assert len(world.requests) == 30
    with caplog.at_level(logging.WARNING):
        r = _create(client, world, OWN_URL)
        r_upd = _update(client, world, OLD_URL, {"image_url": OWN_URL})
    assert r.status_code == 201 and r_upd.status_code == 200
    assert len(world.requests) == 30  # no 31st LLM call
    assert len(_warnings(caplog, "image description skipped: hourly limit")) == 2
    assert SHOP in _warnings(caplog, "hourly limit")[0].getMessage()
    # the update still clears the stale description; the create leaves the default
    assert world.desc_updates[-1].payload == {"image_description": None}
    assert len(world.desc_updates) == 31  # 30 descriptions + 1 clear


def test_the_limit_is_per_shop(client, world):
    for _ in range(30):
        assert _create(client, world, OWN_URL).status_code == 201
    other_url = f"{PUBLIC}/{OTHER_SHOP}/a.png"
    assert _create(client, world, other_url, shop=OTHER_SHOP).status_code == 201
    assert len(world.requests) == 31
    assert world.desc_updates[-1].payload == {"image_description": DESC}
    assert ("eq", "shop_id", OTHER_SHOP) in _filters(world.desc_updates[-1])


# ---------------------------------------------------------------------------
# authorization
# ---------------------------------------------------------------------------
def test_create_in_someone_elses_shop_is_404_without_llm(client, world):
    world.user_db.responses[("shops", "select")] = []  # RLS: the shop is not the user's
    world.db.responses[("products", "insert")] = [_row(OWN_URL)]
    r = client.post("/products", json={"shop_id": SHOP, "name": "x", "price": 1, "quantity": 1,
                                       "image_url": OWN_URL})
    assert r.status_code == 404
    assert world.requests == [] and world.downloads == []
    assert world.db.calls_for("products", "insert") == [] and world.desc_updates == []


def test_update_of_someone_elses_product_is_404_without_llm(client, world):
    world.user_db.responses[("products", "select")] = []
    world.user_db.responses[("products", "update")] = []  # RLS: 0 rows
    r = client.put(f"/products/{PRODUCT}", json={"image_url": OWN_URL})
    assert r.status_code == 404
    assert world.requests == [] and world.downloads == [] and world.desc_updates == []


# ---------------------------------------------------------------------------
# ratelimit.allow
# ---------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(ratelimit, "time", c)
    monkeypatch.setattr(ratelimit, "_last_sweep", [c.now])
    return c


def test_allow_true_up_to_the_limit_then_false_without_raising(clock):
    assert [ratelimit.allow("t_allow", "k", 3, 3600) for _ in range(5)] == [True, True, True, False, False]
    assert len(ratelimit._HITS["t_allow"]["k"]) == 3  # a refusal records nothing


def test_allow_window_expires(clock):
    for _ in range(2):
        assert ratelimit.allow("t_allow", "k", 2, 100) is True
    assert ratelimit.allow("t_allow", "k", 2, 100) is False
    clock.now += 100.5
    assert ratelimit.allow("t_allow", "k", 2, 100) is True


def test_allow_keys_and_buckets_are_independent(clock):
    assert ratelimit.allow("t_allow", "a", 1, 60) is True
    assert ratelimit.allow("t_allow", "a", 1, 60) is False
    assert ratelimit.allow("t_allow", "b", 1, 60) is True
    assert ratelimit.allow("t_other", "a", 1, 60) is True


def test_allow_registers_its_window_so_the_sweep_keeps_long_entries(clock):
    ratelimit.allow("t_window", "k", 1, 3600)
    assert ratelimit._WINDOWS["t_window"] >= 3600
    clock.now += 400  # past the 5 minute sweep, inside the hour
    ratelimit._sweep(clock.now)
    assert len(ratelimit._HITS["t_window"]["k"]) == 1  # the sweep ran but kept the entry
    assert ratelimit._last_sweep[0] == clock.now
    assert ratelimit.allow("t_window", "k", 1, 3600) is False


def test_allow_shares_hits_with_the_existing_limiter(clock):
    from fastapi import HTTPException

    assert ratelimit.allow("t_shared", "k", 1, 60) is True
    with pytest.raises(HTTPException) as exc:
        ratelimit._hit("t_shared", "k", 1, 60)
    assert exc.value.status_code == 429
