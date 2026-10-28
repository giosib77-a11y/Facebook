"""S15-3: the blind provider comparison script, offline, with fake Claude / OpenAI clients.

The script itself is never run from a shell by agents; here only main(argv) and its functions
are called, with fake SDK clients, a spy on get_service_client and a tmp out-dir.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import llm, prompt
from scripts import compare_providers as cp

SHOP_ID = "00000000-0000-4000-8000-000000000015"
CLAUDE_KEY = "test-anthropic-key-not-real"
OPENAI_KEY = "test-openai-key-not-real"
FORBIDDEN = ("claude", "anthropic", "openai", "gpt", "haiku", "luna")

ANSWER_RE = re.compile(r"^### (Q\d\d) — ([AB])\n\n(`{3,})text\n(.*?)\n\3\n", re.DOTALL | re.MULTILINE)


class Env:
    """Fake provider clients + settings patch + spies."""

    def __init__(self, monkeypatch, **update):
        base = llm.get_settings().model_copy(
            update={"anthropic_api_key": CLAUDE_KEY, "openai_api_key": OPENAI_KEY})
        self.settings = base.model_copy(update=update)
        monkeypatch.setattr(cp, "get_settings", lambda: self.settings)
        monkeypatch.setattr(llm, "get_settings", lambda: self.settings)
        self.service_client_calls = 0
        self.factory_calls = 0
        self.counter = 0
        self.claude_calls = 0
        self.produced: dict[str, str] = {}  # answer text -> provider
        self.requests: list[tuple[str, dict]] = []
        self.claude_fail_at: int | None = None  # n-th Claude call raises
        self.openai_empty = False
        self.text_override: str | None = None

        def spy():
            self.service_client_calls += 1
            raise AssertionError("get_service_client must not be used")

        monkeypatch.setattr(llm, "get_service_client", spy)

        def claude_factory(s):
            self.factory_calls += 1
            return SimpleNamespace(messages=SimpleNamespace(create=self._claude_create))

        def openai_factory(s):
            self.factory_calls += 1
            return SimpleNamespace(responses=SimpleNamespace(create=self._openai_create))

        monkeypatch.setattr(llm, "_anthropic_client", claude_factory)
        monkeypatch.setattr(llm, "_openai_client", openai_factory)

    def _text(self, provider, kwargs):
        self.counter += 1
        self.requests.append((provider, kwargs))
        text = self.text_override if self.text_override is not None else f"ANS-{self.counter:03d}"
        self.produced[text] = provider
        return text

    def _claude_create(self, **kwargs):
        self.claude_calls += 1
        text = self._text("claude", kwargs)
        if self.claude_fail_at == self.claude_calls:
            raise TimeoutError("boom")
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=4000,
                                  cache_creation_input_tokens=2000))

    def _openai_create(self, **kwargs):
        text = self._text("openai", kwargs)
        if self.openai_empty:
            text = ""
        return SimpleNamespace(
            output_text=text,
            usage=SimpleNamespace(input_tokens=5000, output_tokens=200,
                                  input_tokens_details=SimpleNamespace(cached_tokens=4000, cache_write_tokens=0)))


def run(tmp_path, *extra, out_sub=None):
    out = tmp_path / out_sub if out_sub else tmp_path
    code = cp.main(["--out-dir", str(out), "--delay", "0", *extra])
    return code, out


def read_outputs(out):
    md = (out / cp.OUTPUT_NAME).read_text(encoding="utf-8")
    key = json.loads((out / cp.KEY_NAME).read_text(encoding="utf-8"))
    return md, key


def answers_of(md):
    return {(m.group(1), m.group(2)): m.group(4) for m in ANSWER_RE.finditer(md)}


@pytest.fixture
def env(monkeypatch):
    return Env(monkeypatch)


def all_ids():
    _, _, questions = cp.load_data()
    return [q["id"] for q in questions]


# (1) full run -----------------------------------------------------------------------------
def test_full_run(env, tmp_path):
    code, out = run(tmp_path, "--seed", "15")
    assert code == 0
    md, key = read_outputs(out)
    assert len(env.requests) == 80
    assert len(re.findall(r"^## Q\d\d · ", md, re.MULTILINE)) == 40
    for qid in all_ids():
        assert f"### {qid} — A" in md and f"### {qid} — B" in md
    answers = answers_of(md)
    assert len(answers) == 80
    for (qid, label), text in answers.items():
        assert env.produced[text] == key["mapping"][qid][label]
    assert key["mapping"] == cp.assign_labels(all_ids(), 15)
    assert key["models"] == {"claude": "claude-haiku-5-5", "openai": "gpt-6-luna"}
    for provider, request in env.requests:
        if provider == "claude":
            assert request["model"] == "claude-haiku-5-5"
        else:
            assert request["model"] == "gpt-6-luna"
            assert request["prompt_cache_key"] == f"shop:{SHOP_ID}"
    assert env.service_client_calls == 0


# (2) blind --------------------------------------------------------------------------------
def test_output_is_blind(env, tmp_path):
    code, out = run(tmp_path)
    assert code == 0
    md, _ = read_outputs(out)
    low = md.lower()
    for word in (*FORBIDDEN, env.settings.claude_model.lower(), env.settings.openai_model.lower()):
        assert word not in low


# (3) seed ---------------------------------------------------------------------------------
def test_assign_labels_seed():
    ids = all_ids()
    first = cp.assign_labels(ids, 15)
    assert first == cp.assign_labels(ids, 15)
    assert first != cp.assign_labels(ids, 16)
    assert all(sorted(pair.values()) == sorted(llm.PROVIDERS) and set(pair) == {"A", "B"}
               for pair in first.values())
    assert {m["A"] for m in first.values()} == set(llm.PROVIDERS)


# (4) cost ---------------------------------------------------------------------------------
def test_cost_estimates(env, tmp_path):
    claude = llm.Usage(input_tokens=1000, output_tokens=200, cache_read_tokens=4000, cache_write_tokens=2000)
    openai = llm.Usage(input_tokens=1000, output_tokens=200, cache_read_tokens=4000, cache_write_tokens=0)
    assert cp.estimate_cost("claude", claude) == pytest.approx(0.00049)
    assert cp.estimate_cost("openai", openai) == pytest.approx(0.00024)
    assert cp.PRICES["openai"]["unverified"] is True

    code, out = run(tmp_path)
    assert code == 0
    md, key = read_outputs(out)
    assert "$0.000490" in md and "$0.000240" in md
    assert "UNVERIFIED" in md.split("## Q01")[0]
    assert key["totals"]["claude"]["cost_usd"] == pytest.approx(40 * 0.00049)
    assert key["totals"]["openai"]["cost_usd"] == pytest.approx(40 * 0.00024)
    assert key["totals"]["openai"]["input_tokens"] == 40 * 1000  # normalized to uncached
    assert key["prices_match_models"] == {"claude": True, "openai": True}


# (5) missing keys -------------------------------------------------------------------------
@pytest.mark.parametrize("empty,missing,present", [
    ("openai_api_key", "OPENAI_API_KEY", CLAUDE_KEY),
    ("anthropic_api_key", "ANTHROPIC_API_KEY", OPENAI_KEY),
])
def test_missing_key(monkeypatch, tmp_path, capsys, empty, missing, present):
    env = Env(monkeypatch, **{empty: ""})
    code, out = run(tmp_path, out_sub="out")
    err = capsys.readouterr().err
    assert code == 2
    assert not out.exists() and list(tmp_path.iterdir()) == []
    assert missing in err
    other = "ANTHROPIC_API_KEY" if missing == "OPENAI_API_KEY" else "OPENAI_API_KEY"
    assert other not in err
    assert present not in err
    assert env.factory_calls == 0


# (6) one failing call does not stop the run -----------------------------------------------
def test_call_error_does_not_stop(env, tmp_path):
    env.claude_fail_at = 5
    code, out = run(tmp_path)
    assert code == 0
    md, key = read_outputs(out)
    assert len(re.findall(r"^## Q\d\d · ", md, re.MULTILINE)) == 40
    qid = "Q05"
    claude_label = next(lbl for lbl, p in key["mapping"][qid].items() if p == "claude")
    assert answers_of(md)[(qid, claude_label)] == "[error: TimeoutError]"
    assert "boom" not in md and "boom" not in json.dumps(key)
    assert key["errors"] == {qid: {"claude": {"class": "TimeoutError", "status": None}}}
    assert key["totals"]["claude"]["errors"] == 1
    assert key["totals"]["openai"]["errors"] == 0


# (7) empty answer -------------------------------------------------------------------------
def test_empty_answer(env, tmp_path):
    env.openai_empty = True
    code, out = run(tmp_path, "--limit", "2")
    assert code == 0
    md, key = read_outputs(out)
    for qid, pair in key["mapping"].items():
        label = next(lbl for lbl, p in pair.items() if p == "openai")
        assert answers_of(md)[(qid, label)] == "[empty answer]"
    assert key["totals"]["openai"]["empty"] == 2
    assert key["totals"]["openai"]["output_tokens"] == 400  # usage still counted
    assert "- empty answers: 2" in md


# (8) handoff token ------------------------------------------------------------------------
def test_handoff_token_is_stripped(env, tmp_path):
    env.text_override = "ერთ წამში, ოპერატორი დაგიკავშირდებათ 🙏 [[HANDOFF]]"
    code, out = run(tmp_path, "--limit", "1")
    assert code == 0
    md, _ = read_outputs(out)
    assert md.count("handoff: yes") == 2
    assert "[[HANDOFF]]" not in md


# (9) --limit ------------------------------------------------------------------------------
def test_limit(env, tmp_path):
    code, out = run(tmp_path, "--limit", "3")
    assert code == 0
    md, key = read_outputs(out)
    assert len(env.requests) == 6
    assert len(re.findall(r"^## Q\d\d · ", md, re.MULTILINE)) == 3
    expected = cp.assign_labels(all_ids(), 15)
    assert key["mapping"] == {qid: expected[qid] for qid in all_ids()[:3]}
    assert key["questions"] == 3


# (10) --dry-run ---------------------------------------------------------------------------
def test_dry_run(monkeypatch, tmp_path, capsys):
    env = Env(monkeypatch, anthropic_api_key="", openai_api_key="")

    def boom(s):
        raise AssertionError("factory must not be called in --dry-run")

    monkeypatch.setattr(llm, "_anthropic_client", boom)
    monkeypatch.setattr(llm, "_openai_client", boom)
    code, _ = run(tmp_path, "--dry-run")
    out = capsys.readouterr().out
    assert code == 0
    assert env.factory_calls == 0 and env.requests == []
    assert list(tmp_path.iterdir()) == []
    assert len(re.findall(r"^Q\d\d \w+: L1 \d+ · L2 \d+ · history \d+ · final \d+ chars · images \d+$",
                          out, re.MULTILINE)) == 40


# (11) prompt parity with the bot path -----------------------------------------------------
def test_prompt_parity():
    shop, products, questions = cp.load_data()
    ref_products = [p for p in products if p.get("image")]
    layer2s = set()
    for q in questions:
        p = cp.build_question_prompt(shop, products, q)
        assert p.layer1 == prompt.LAYER1
        layer2s.add(p.layer2)
        chars = (len(p.layer1) + len(p.layer2) + sum(len(t["text"]) for t in p.history)
                 + sum(len(x["text"]) for x in p.final if x["type"] == "text"))
        assert chars <= prompt.MAX_PROMPT_CHARS
        images = [x for x in p.final if x["type"] == "image"]
        if q.get("image"):
            assert len(images) == 1 + len(ref_products)
            data, mime = cp.load_image(q["image"])
            assert images[0]["data"] == data and images[0]["mime"] == "image/png"
            texts = [x["text"] for x in p.final if x["type"] == "text"]
            for rp in ref_products:
                assert any(t.startswith(f"• {rp['name']} — {rp['price']}") and f"(SKU: {rp['sku']})" in t
                           for t in texts)
        else:
            assert images == []
    assert len(layer2s) == 1


# (12) .gitignore --------------------------------------------------------------------------
def test_gitignore_lines():
    lines = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "backend/scripts/compare_output.md" in lines
    assert "backend/scripts/compare_key.json" in lines


# extra: data / image errors ---------------------------------------------------------------
def test_load_image_rejects_bad_files():
    for bad in ("../x.png", "a/b.png", "", "missing.png"):
        with pytest.raises(ValueError):
            cp.load_image(bad)
    assert cp.load_image("prod_tshirt.png")[1] == "image/png"


def test_load_data_reports_missing_photo(tmp_path):
    data = json.loads(cp.DATA_PATH.read_text(encoding="utf-8"))
    photo_q = next(q for q in data["questions"] if q.get("image"))
    photo_q["image"] = "nope.png"
    bad = tmp_path / "q.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=photo_q["id"]):
        cp.load_data(bad)


def test_data_error_returns_2_without_calls(env, tmp_path, monkeypatch, capsys):
    def broken(path=cp.DATA_PATH):
        raise ValueError("Q99: broken")

    monkeypatch.setattr(cp, "load_data", broken)
    code, _ = run(tmp_path)
    assert code == 2 and "Q99: broken" in capsys.readouterr().err
    assert env.requests == [] and list(tmp_path.iterdir()) == []
