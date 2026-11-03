"""A-022 (N-13): production-ში /docs, /redoc, /openapi.json გამორთულია (API-ს რუკა არ ჩანს)."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main

PROD = SimpleNamespace(is_production=True)
DEV = SimpleNamespace(is_production=False)


def test_docs_kwargs_production_disables_all():
    assert main._docs_kwargs(PROD) == {"docs_url": None, "redoc_url": None, "openapi_url": None}


def test_docs_kwargs_dev_keeps_defaults():
    assert main._docs_kwargs(DEV) == {}


def test_production_app_returns_404_for_docs_endpoints():
    app = FastAPI(**main._docs_kwargs(PROD))
    c = TestClient(app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 404, path


def test_dev_app_serves_openapi_and_docs():
    app = FastAPI(**main._docs_kwargs(DEV))
    c = TestClient(app)
    assert c.get("/openapi.json").status_code == 200
    assert c.get("/docs").status_code == 200


def test_current_test_env_main_app_serves_openapi():
    assert not main.settings.is_production
    assert TestClient(main.app).get("/openapi.json").status_code == 200
