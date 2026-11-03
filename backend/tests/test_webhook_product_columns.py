"""A-021: the webhook loads only the product columns the bot uses, not select("*")."""
import app.api.webhook as webhook

PAGE_ID = "1234567890"
SHOP = {"id": "22222222-2222-2222-2222-222222222222", "bot_enabled": True, "facebook_page_token": "enc"}
BOT_FIELDS = {"id", "name", "price", "quantity", "sku", "description", "image_url", "image_description"}


def _harness(monkeypatch, db):
    FakeQuery = type(db.table("x"))  # the conftest class pytest actually loaded
    real_select, real_execute = FakeQuery.select, FakeQuery.execute
    selects = []

    def select(self, *columns, **kwargs):
        self.columns = columns
        return real_select(self, *columns, **kwargs)

    def execute(self):
        if self.table == "products" and self.op == "select":
            selects.append(self.columns)
            if "image_description" in ",".join(self.columns) and db.errors.get("missing_0028"):
                raise db.errors["missing_0028"]
        return real_execute(self)

    monkeypatch.setattr(FakeQuery, "select", select)
    monkeypatch.setattr(FakeQuery, "execute", execute)
    monkeypatch.setattr(webhook, "get_service_client", lambda: db)
    monkeypatch.setattr(webhook, "decrypt", lambda token: "page-token")
    db.responses[("shops", "select")] = [SHOP]
    db.responses[("products", "select")] = [{"id": "p1", "name": "Shirt"}]
    return selects


def _run():
    # no messaging events: processing stops right after the shop + products load
    webhook._process_events({"object": "page", "entry": [{"id": PAGE_ID, "messaging": []}]})


def _fields(columns) -> set[str]:
    return {c.strip() for c in ",".join(columns).split(",")}


def test_products_loaded_with_explicit_bot_columns(monkeypatch, service_db):
    selects = _harness(monkeypatch, service_db)
    _run()
    (cols,) = selects
    assert "*" not in ",".join(cols)
    assert _fields(cols) == BOT_FIELDS


def test_products_fallback_without_image_description_before_0028(monkeypatch, service_db):
    selects = _harness(monkeypatch, service_db)
    service_db.errors["missing_0028"] = RuntimeError("column products.image_description does not exist")
    _run()
    assert len(selects) == 2
    assert _fields(selects[1]) == BOT_FIELDS - {"image_description"}
