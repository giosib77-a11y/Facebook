"""A-031 (N-21): /panel მხოლოდ frontend/dist-იდან; frontend/ წყაროს fallback მთლიანად წაშლილია."""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main


def test_no_dist_mounts_nothing_and_serves_no_source(tmp_path, caplog):
    fe = tmp_path / "frontend"
    (fe / "public").mkdir(parents=True)
    (fe / "index.html").write_text("<html>src</html>")
    (fe / "package.json").write_text('{"name": "secret-src"}')
    (fe / "public" / "config.js").write_text("window.X = 1;")

    app = FastAPI()
    with caplog.at_level(logging.WARNING, logger="app"):
        assert main._mount_panel(app, fe / "dist") is False
    assert any(
        r.levelno == logging.WARNING and "frontend/dist/index.html missing" in r.getMessage()
        for r in caplog.records
    )

    c = TestClient(app)
    for path in ("/panel/", "/panel/package.json", "/panel/config.js", "/panel/index.html"):
        assert c.get(path).status_code == 404, path


def test_dist_without_index_html_is_not_mounted(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "a-123.js").write_text("x")
    app = FastAPI()
    assert main._mount_panel(app, dist) is False
    assert TestClient(app).get("/panel/assets/a-123.js").status_code == 404


def test_dist_is_mounted_with_cache_headers(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>dist</html>")
    (dist / "assets" / "a-123.js").write_text("console.log(1)")

    app = FastAPI()
    assert main._mount_panel(app, dist) is True
    c = TestClient(app)

    r = c.get("/panel/")
    assert r.status_code == 200
    assert "dist" in r.text
    assert "no-store" in r.headers["cache-control"]

    r = c.get("/panel/assets/a-123.js")
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]


def test_main_app_still_serves_panel_from_repo_dist():
    assert TestClient(main.app).get("/panel/").status_code == 200


def test_main_source_has_no_fallback_code():
    text = Path(main.__file__).read_text(encoding="utf-8")
    assert "extra_dirs" not in text
    assert '_FRONTEND_SRC / "public"' not in text
