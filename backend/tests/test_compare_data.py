"""Data checks for the Stage 15 provider-comparison fixture (scripts/compare_questions.json)."""
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from app.services import prompt

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
DATA_FILE = SCRIPTS / "compare_questions.json"
ASSETS = SCRIPTS / "compare_assets"

EXPECTED_COUNTS = {
    "stock_price": 6,
    "out_of_stock": 3,
    "price_on_request": 1,
    "knowledge": 5,
    "knowledge_missing": 2,
    "ambiguous": 3,
    "multi_turn": 4,
    "order": 2,
    "handoff": 3,
    "off_topic": 2,
    "language": 2,
    "injection": 3,
    "photo": 4,
}
FORBIDDEN = ("claude", "anthropic", "openai", "gpt", "haiku", "luna")
MAX_IMAGE_BYTES = 100 * 1024


@pytest.fixture(scope="module")
def data():
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def test_forty_questions_with_sequential_ids(data):
    ids = [q["id"] for q in data["questions"]]
    assert len(ids) == 40
    assert ids == [f"Q{i:02d}" for i in range(1, 41)]
    assert len(set(ids)) == 40


def test_category_counts(data):
    assert dict(Counter(q["category"] for q in data["questions"])) == EXPECTED_COUNTS


def test_question_schema(data):
    for q in data["questions"]:
        qid = q["id"]
        assert isinstance(q["message"], str), qid
        if not q["message"]:
            assert q.get("image"), f"{qid}: empty message needs an image"
        if "history" in q:
            h = q["history"]
            assert isinstance(h, list) and h, qid
            assert h[0]["role"] == "user", qid
            for turn in h:
                assert turn["role"] in ("user", "bot"), qid
                assert isinstance(turn["content"], str) and turn["content"].strip(), qid
        if q["category"] == "multi_turn":
            assert len(q.get("history", [])) >= 2, qid
        assert ("image" in q) == (q["category"] == "photo"), qid
        exp = q["expect"]
        assert exp["handoff"] in (True, False, None), qid
        assert isinstance(exp["note"], str) and exp["note"].strip(), qid
        if q["category"] == "handoff":
            assert exp["handoff"] is True, qid
        if q["category"] == "stock_price":
            assert exp["handoff"] is False, qid


def test_images_exist_are_valid_and_all_used(data):
    names = [q["image"] for q in data["questions"] if "image" in q]
    names += [p["image"] for p in data["products"] if "image" in p]
    assert names
    for name in names:
        assert name == Path(name).name and "/" not in name and "\\" not in name and ".." not in name, name
        path = ASSETS / name
        assert path.is_file(), name
        raw = path.read_bytes()
        assert len(raw) <= MAX_IMAGE_BYTES, name
        if name.lower().endswith(".png"):
            assert raw.startswith(b"\x89PNG\r\n\x1a\n"), name
        elif name.lower().endswith((".jpg", ".jpeg")):
            assert raw.startswith(b"\xff\xd8\xff"), name
        else:
            pytest.fail(f"unexpected extension: {name}")
    on_disk = {p.name for p in ASSETS.iterdir() if p.is_file()}
    assert on_disk == set(names), f"orphan or missing assets: {on_disk ^ set(names)}"


def test_products(data):
    products = data["products"]
    assert len(products) <= prompt.RETRIEVE_LIMIT
    assert len({p["id"] for p in products}) == len(products)
    assert sum(1 for p in products if p["quantity"] == 0) >= 3
    assert sum(1 for p in products if p["price"] == 0) == 1
    with_image = [p for p in products if "image" in p]
    assert len(with_image) == 8
    assert any(p["quantity"] == 0 for p in with_image)


def _check_description_format(text, where):
    assert isinstance(text, str) and len(text) <= 500, where
    lines = text.split("\n")
    assert len(lines) == 2, where
    assert lines[0].startswith("EN: ") and lines[1].startswith("KA: "), where
    assert lines[0][4:].strip() and lines[1][4:].strip(), where


def test_photo_products_have_descriptions(data):
    for p in data["products"]:
        if "image" in p:
            _check_description_format(p.get("image_description"), p["id"])
        else:
            assert "image_description" not in p, p["id"]


def test_customer_photos_have_descriptions(data):
    for q in data["questions"]:
        if q["category"] == "photo":
            _check_description_format(q.get("photo_description"), q["id"])
        else:
            assert "photo_description" not in q, q["id"]


def test_shop(data):
    shop = data["shop"]
    assert shop["currency"] == "GEL"
    assert shop["bot_language"] == "auto"
    assert shop["knowledge"].strip()


def test_knowledge_faq(data):
    shop = data["shop"]
    faq = shop["knowledge_faq"]
    assert faq.strip()
    assert len(faq) <= prompt.KNOWLEDGE_FAQ_MAX_CHARS
    lines = [ln for ln in faq.splitlines() if ln.strip()]
    assert len(lines) >= 2 and len(lines) % 2 == 0
    for i, ln in enumerate(lines):
        assert ln.startswith("Q: " if i % 2 == 0 else "A: "), ln
    for num in re.findall(r"\d+", faq):
        assert num in shop["knowledge"], f"invented number: {num}"


def test_no_provider_names_in_text():
    text = DATA_FILE.read_text(encoding="utf-8").lower()
    for word in FORBIDDEN:
        assert word not in text, word
