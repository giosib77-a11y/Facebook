"""Blind comparison of the two LLM providers (Claude vs OpenAI) on 40 demo-shop questions.

Each question goes through the production path (graph.run_turn: templates, tool loop, clean-up),
once per provider, against a fictional shop from compare_questions.json; only the product photos
come from local files. Tools run on the fictional data. Nothing touches Supabase, Graph or
llm_usage (usage recording is switched off). Answers are written to compare_output.md with
random A/B labels per question; the label -> provider mapping is in compare_key.json.

Run (OWNER ONLY, real API calls and cost; both ANTHROPIC_API_KEY and OPENAI_API_KEY needed),
from backend/:
    .venv/Scripts/python.exe -m scripts.compare_providers [--seed N] [--limit N] [--delay S]
                                                          [--out-dir DIR] [--dry-run]

Agents never run this script - tests import it with fake clients. The output files are
gitignored.
"""
import argparse
import json
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.services import bot, graph, llm, prompt, vision

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_PATH = SCRIPT_DIR / "compare_questions.json"
ASSETS_DIR = SCRIPT_DIR / "compare_assets"
OUTPUT_NAME = "compare_output.md"
KEY_NAME = "compare_key.json"
DEFAULT_SEED = 15
DEFAULT_DELAY = 1.0

EMPTY_TEXT = "[empty answer]"

RUBRIC = (
    ("facts", "stock, price and shop knowledge come only from the shop data "
              "(on a photo question: the right product)"),
    ("language", "natural Georgian, or the customer's language when it is not Georgian"),
    ("brevity", "short, no markdown"),
    ("handoff", "hands over to a human when it should, and only then"),
)

# USD per 1M tokens. Simplifications: the 1h write of the L1 layer is priced as 1.25x (it is
# written at most once an hour); the 5x price of requests over 100K tokens is not modelled
# (prompts are capped by prompt.MAX_PROMPT_CHARS); image tokens are inside input_tokens.
PRICES = {
    "claude": {
        "model": "claude-haiku-5-5",
        "input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125,
        "unverified": False,
        "source": "DEPLOYMENT.md + PROJECT.md Decision Log (2026-10-28)",
    },
    # UNVERIFIED: third-party figures, check OpenAI pricing page
    "openai": {
        "model": "gpt-6-luna",
        "input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.10,
        "unverified": True,
        "source": "third-party figures; cache write assumed equal to input price",
    },
}


@dataclass
class Answer:
    text: str
    handoff: bool
    usage: llm.Usage = field(default_factory=llm.Usage)
    latency_s: float = 0.0
    cost_usd: float = 0.0
    error: dict | None = None
    empty: bool = False


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_image(name: str) -> tuple[bytes, str]:
    """Local demo image -> (bytes, mime). The mime comes from the magic bytes."""
    if not isinstance(name, str) or not name or Path(name).name != name or name in (".", ".."):
        raise ValueError(f"bad image name: {name!r}")
    try:
        data = (ASSETS_DIR / name).read_bytes()
    except OSError as exc:
        raise ValueError(f"image not readable: {name} ({type(exc).__name__})") from exc
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return data, "image/jpeg"
    raise ValueError(f"image is neither PNG nor JPEG: {name}")


def _check_description(item: dict, key: str, where: str) -> None:
    """Optional photo description: a string of at most vision.DESCRIPTION_MAX_CHARS."""
    value = item.get(key) if isinstance(item, dict) else None
    if value is not None and (not isinstance(value, str) or len(value) > vision.DESCRIPTION_MAX_CHARS):
        raise ValueError(f"{where}: {key} must be a string of at most {vision.DESCRIPTION_MAX_CHARS} chars")


def load_data(path: Path = DATA_PATH) -> tuple[dict, list[dict], list[dict]]:
    """compare_questions.json -> (shop, products, questions); minimal validation."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read {Path(path).name}: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise ValueError("data file must be a JSON object")
    for key in ("shop", "products", "questions"):
        if key not in data:
            raise ValueError(f"missing key: {key}")
    shop, products, questions = data["shop"], data["products"], data["questions"]
    if not isinstance(shop, dict) or not shop.get("id"):
        raise ValueError("shop must be an object with an id")
    if not isinstance(products, list) or not isinstance(questions, list) or not questions:
        raise ValueError("products and questions must be non-empty lists")
    for p in products:
        if not isinstance(p, dict) or not p.get("id") or not p.get("name"):
            raise ValueError("every product needs an id and a name")
        _check_description(p, "image_description", f"product {p['id']}")
        if p.get("image"):
            try:
                load_image(p["image"])
            except ValueError as exc:
                raise ValueError(f"product {p['id']}: {exc}") from exc
    seen = set()
    for q in questions:
        qid = q.get("id") if isinstance(q, dict) else None
        if not qid or qid in seen:
            raise ValueError(f"question without a unique id: {qid!r}")
        seen.add(qid)
        if not q.get("category") or not isinstance(q.get("message"), str):
            raise ValueError(f"{qid}: category and message are required")
        if not isinstance(q.get("expect"), dict):
            raise ValueError(f"{qid}: expect is required")
        _check_description(q, "photo_description", qid)
        if q.get("image"):
            try:
                load_image(q["image"])
            except ValueError as exc:
                raise ValueError(f"{qid}: {exc}") from exc
        elif not q["message"].strip():
            raise ValueError(f"{qid}: empty message without an image")
    return shop, products, questions


# ---------------------------------------------------------------------------
# Prompt / calls
# ---------------------------------------------------------------------------
def local_refs_loader(relevant: list[dict], images) -> list:
    """graph refs_loader: product photos from local files instead of Storage (the cap and the
    label are the bot's own)."""
    refs = []
    for p in relevant:
        if not p.get("image"):
            continue
        if len(refs) >= bot.MAX_REF_IMAGES:
            break
        refs.append((bot.product_ref_label(p), load_image(p["image"])))
    return refs


def question_args(q: dict) -> tuple[str, list | None, list | None]:
    """(message, history, images) of a question, as the webhook would hand them to the graph."""
    images = [load_image(q["image"])] if q.get("image") else None
    return q["message"], q.get("history"), images


def build_question_prompt(shop: dict, products: list[dict], q: dict) -> prompt.Prompt:
    """The prompt the production graph builds for this question (--dry-run and the parity test)."""
    message, history, images = question_args(q)
    # Production describes the customer photo (inside run_turn) only for a big described catalogue;
    # here the hand-written description stands in for it, under the same condition.
    description = q.get("photo_description") if images and graph.wants_photo_description(products) else None
    return graph.build_turn_prompt(
        shop, products, message, history, images, refs_loader=local_refs_loader,
        photo_description=description)


def assign_labels(question_ids: list[str], seed: int) -> dict[str, dict[str, str]]:
    """{qid: {"A": provider, "B": provider}} - one RNG, ids in the given order."""
    rng = random.Random(seed)
    out = {}
    for qid in question_ids:
        pair = list(llm.PROVIDERS)
        rng.shuffle(pair)
        out[qid] = {"A": pair[0], "B": pair[1]}
    return out


def estimate_cost(provider: str, usage: llm.Usage) -> float:
    """USD estimate from PRICES (llm.Usage.input_tokens is already uncached)."""
    pr = PRICES[provider]
    return (
        usage.input_tokens * pr["input"]
        + usage.output_tokens * pr["output"]
        + usage.cache_read_tokens * pr["cache_read"]
        + usage.cache_write_tokens * pr["cache_write"]
    ) / 1e6


def error_category(status) -> str:
    """Provider-neutral error label for the blind output (the exact class/status go to the key)."""
    if not isinstance(status, int):
        return "no response"
    if status == 429:
        return "rate limit"
    return "server" if status >= 500 else "client"


def sum_usage(calls) -> llm.Usage:
    """Usage of all LLM calls of one turn (0 calls on a template answer -> zeros)."""
    total = llm.Usage()
    for c in calls:
        total.input_tokens += c.usage.input_tokens
        total.output_tokens += c.usage.output_tokens
        total.cache_read_tokens += c.usage.cache_read_tokens
        total.cache_write_tokens += c.usage.cache_write_tokens
    return total


def ask(provider: str, shop: dict, products: list[dict], q: dict) -> Answer:
    """One provider turn through graph.run_turn (no llm_usage rows). Errors become
    `[error: <category>]` (never the class name or message: they identify the provider);
    KeyboardInterrupt propagates."""
    started = time.perf_counter()
    try:
        message, history, images = question_args(q)
        result = graph.run_turn(
            shop, products, message, history, images, provider=provider,
            record_usage=False, refs_loader=local_refs_loader)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        name = type(exc).__name__
        return Answer(
            text=f"[error: {error_category(status)}]", handoff=False, usage=llm.Usage(),
            latency_s=time.perf_counter() - started, cost_usd=0.0,
            error={"class": name, "status": status if isinstance(status, int) else None},
        )
    latency = time.perf_counter() - started
    usage = sum_usage(result.calls)
    empty = not result.text
    return Answer(
        text=EMPTY_TEXT if empty else result.text, handoff=result.handoff, usage=usage,
        latency_s=latency, cost_usd=estimate_cost(provider, usage), empty=empty,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def _fence_for(text: str) -> str:
    longest = run = 0
    for ch in text:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    return "`" * max(3, longest + 1)


def _expected_line(expect: dict) -> str:
    handoff = {True: "yes", False: "no"}.get(expect.get("handoff"), "either")
    line = f"**Expected:** handoff: {handoff} · {expect.get('note', '')}"
    if expect.get("must_mention"):
        line += f" · must mention: {', '.join(str(x) for x in expect['must_mention'])}"
    return line


def render_output(questions, mapping, answers, seed, created_at) -> str:
    """The blind markdown. `answers` = {qid: {provider: Answer}}. No provider or model name."""
    lines = [
        f"# Blind comparison — {len(questions)} questions",
        "",
        f"- created: {created_at}",
        f"- seed: {seed}",
        "- A/B order is random per question; open compare_key.json only after grading",
        "- Costs are estimates from list prices; some prices are UNVERIFIED",
        "- Rubric (0 = wrong, 1 = partly, 2 = good), per answer:",
    ]
    lines += [f"  - {name}: {desc}" for name, desc in RUBRIC]
    lines.append("")

    calls = errors = empty = 0
    total_cost = 0.0
    for q in questions:
        qid = q["id"]
        lines += [f"## {qid} · {q['category']}", ""]
        for turn in q.get("history") or []:
            who = "customer" if turn.get("role") == "user" else "bot"
            lines.append(f"> {who}: {str(turn.get('content', '')).replace(chr(10), ' ')}")
        if q.get("history"):
            lines.append("")
        if q.get("image"):
            lines += [f"Photo: {q['image']}", ""]
        lines += [f"**Customer:** {q['message'].strip() or '(photo without text)'}", "",
                  _expected_line(q["expect"]), ""]
        for label in ("A", "B"):
            a = answers[qid][mapping[qid][label]]
            calls += 1
            errors += a.error is not None
            empty += a.empty
            total_cost += a.cost_usd
            fence = _fence_for(a.text)
            u = a.usage
            lines += [
                f"### {qid} — {label}", "",
                f"{fence}text", a.text, fence,
                f"handoff: {'yes' if a.handoff else 'no'}",
                "<details><summary>usage</summary>", "",
                f"input {u.input_tokens} · cache read {u.cache_read_tokens} · "
                f"cache write {u.cache_write_tokens} · output {u.output_tokens} · "
                f"{a.latency_s:.2f} s · ${a.cost_usd:.6f}",
                "", "</details>", "",
            ]
        lines += ["| criterion | A (0–2) | B (0–2) |", "|---|---|---|"]
        lines += [f"| {name} |  |  |" for name, _ in RUBRIC]
        lines.append("")
    lines += [
        "## Totals", "",
        f"- questions: {len(questions)}",
        f"- calls: {calls}",
        f"- errors: {errors}",
        f"- empty answers: {empty}",
        f"- total cost (both together): ${total_cost:.6f}",
        "",
    ]
    return "\n".join(lines)


def build_key(s, seed, created_at, questions, mapping, answers) -> dict:
    totals = {}
    errors = {}
    for provider in llm.PROVIDERS:
        rows = [(q["id"], answers[q["id"]][provider]) for q in questions]
        n = len(rows)
        totals[provider] = {
            "calls": n,
            "errors": sum(1 for _, a in rows if a.error is not None),
            "empty": sum(1 for _, a in rows if a.empty),
            "input_tokens": sum(a.usage.input_tokens for _, a in rows),
            "cache_read_tokens": sum(a.usage.cache_read_tokens for _, a in rows),
            "cache_write_tokens": sum(a.usage.cache_write_tokens for _, a in rows),
            "output_tokens": sum(a.usage.output_tokens for _, a in rows),
            "cost_usd": sum(a.cost_usd for _, a in rows),
            "mean_latency_s": (sum(a.latency_s for _, a in rows) / n) if n else 0.0,
        }
        for qid, a in rows:
            if a.error is not None:
                errors.setdefault(qid, {})[provider] = a.error
    models = {"claude": s.claude_model, "openai": s.openai_model}
    return {
        "seed": seed,
        "created_at": created_at,
        "questions": len(questions),
        "models": models,
        "prices": PRICES,
        "prices_match_models": {p: models[p] == PRICES[p]["model"] for p in llm.PROVIDERS},
        "mapping": {q["id"]: mapping[q["id"]] for q in questions},
        "errors": errors,
        "totals": totals,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


def _non_negative_float(value: str) -> float:
    x = float(value)
    if x < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return x


def _final_stats(p: prompt.Prompt) -> tuple[int, int]:
    chars = sum(len(part["text"]) for part in p.final if part["type"] == "text")
    images = sum(1 for part in p.final if part["type"] == "image")
    return chars, images


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="compare_providers", description=__doc__.split("\n")[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--limit", type=_positive_int, default=None)
    ap.add_argument("--delay", type=_non_negative_float, default=DEFAULT_DELAY)
    ap.add_argument("--out-dir", type=Path, default=SCRIPT_DIR)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    try:
        shop, products, all_questions = load_data()
        questions = all_questions[: args.limit] if args.limit else all_questions
        prompts = ({q["id"]: build_question_prompt(shop, products, q) for q in questions}
                   if args.dry_run else {})
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        total = 0
        for q in questions:
            p = prompts[q["id"]]
            final_chars, images = _final_stats(p)
            history_chars = sum(len(t["text"]) for t in p.history)
            total += len(p.layer1) + len(p.layer2) + history_chars + final_chars
            print(f"{q['id']} {q['category']}: L1 {len(p.layer1)} · L2 {len(p.layer2)} · "
                  f"history {history_chars} · final {final_chars} chars · images {images}")
        print(f"{len(questions)} questions, {total} chars in total")
        return 0

    s = get_settings()
    missing = [name for name, value in (
        ("ANTHROPIC_API_KEY", s.anthropic_api_key), ("OPENAI_API_KEY", s.openai_api_key),
    ) if not value]
    if missing:
        print(f"error: {', '.join(missing)} not set — შედარებას ორივე key სჭირდება (README §9)",
              file=sys.stderr)
        return 2
    for provider, model in (("claude", s.claude_model), ("openai", s.openai_model)):
        if model != PRICES[provider]["model"]:
            print(f"WARNING: configured model {model!r} differs from the price table "
                  f"({PRICES[provider]['model']!r}); cost estimates may be wrong", file=sys.stderr)

    seed = args.seed
    mapping = assign_labels([q["id"] for q in all_questions], seed)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    answers: dict[str, dict[str, Answer]] = {}
    total_calls = len(questions) * len(llm.PROVIDERS)
    done = 0
    # llm.py warnings (retry with the exception class, "refused" — Claude only) would reach the
    # console next to [i/N] and reveal the provider; silence the "app" logger for the call loop.
    app_logger = logging.getLogger("app")
    null_handler = logging.NullHandler()
    # graph.py's "bot turn: ..." INFO line goes to stdout through the app's own handler, so the
    # logger is disabled outright (handlers/propagate are restored below).
    old_propagate, old_disabled = app_logger.propagate, app_logger.disabled
    app_logger.addHandler(null_handler)
    app_logger.propagate = False
    app_logger.disabled = True
    try:
        for i, q in enumerate(questions, 1):
            print(f"[{i}/{len(questions)}] {q['id']}")
            answers[q["id"]] = {}
            for provider in llm.PROVIDERS:
                answers[q["id"]][provider] = ask(provider, shop, products, q)
                done += 1
                if args.delay > 0 and done < total_calls:
                    time.sleep(args.delay)
    finally:
        app_logger.removeHandler(null_handler)
        app_logger.propagate = old_propagate
        app_logger.disabled = old_disabled

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path, key_path = out_dir / OUTPUT_NAME, out_dir / KEY_NAME
    out_path.write_text(
        render_output(questions, mapping, answers, seed, created_at), encoding="utf-8", newline="\n")
    key = build_key(s, seed, created_at, questions, mapping, answers)
    key_path.write_text(
        json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    n_errors = sum(1 for per_q in answers.values() for a in per_q.values() if a.error is not None)
    cost = sum(a.cost_usd for per_q in answers.values() for a in per_q.values())
    print(f"written: {out_path}")
    print(f"written: {key_path}")
    print(f"calls: {total_calls}, errors: {n_errors}, estimated total cost: ${cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
