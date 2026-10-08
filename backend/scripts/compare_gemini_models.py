"""One-off: compare two Gemini models on the bot's real system prompt (T12).

Run from repo root (Git Bash / PowerShell):
    backend/.venv/Scripts/python.exe backend/scripts/compare_gemini_models.py

--dry-run builds the prompt and prints the question list; no API call, no key access, no .env read.
The API key is NEVER printed or written anywhere (errors are sanitized).
"""
import argparse
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services import bot  # noqa: E402  (imports config lazily; no Settings instance at import)

# Mirrors get_bot_reply() in app/services/bot.py (values are inline there, not importable).
TEMPERATURE = 0.3
MAX_OUTPUT_TOKENS = 800

SHOP = {
    "id": "00000000-0000-0000-0000-000000000000",
    "name": "სტილი",
    "currency": "GEL",
    "description": "ტანსაცმლისა და აქსესუარების მაღაზია თბილისში",
    "bot_language": "auto",
    "knowledge": (
        "მიწოდება: თბილისში 5 ლარი, 1-2 სამუშაო დღე; რეგიონებში 8 ლარი, 2-4 დღე.\n"
        "გადახდა: ნაღდი ფულით კურიერთან ან ბარათით ონლაინ.\n"
        "დაბრუნება: 14 დღის განმავლობაში, თუ ნივთი გამოუყენებელია."
    ),
}

PRODUCTS = [
    {"name": "წითელი მაისური Nike", "price": 89, "quantity": 12, "sku": "TS-001", "description": "ბამბის, ზომები S-XL"},
    {"name": "თეთრი პერანგი", "price": 65, "quantity": 5, "sku": "SH-002", "description": "კლასიკური ჭრილი, ზომები M-XXL"},
    {"name": "შავი ჯინსი Levi's", "price": 150, "quantity": 0, "sku": "JN-003", "description": "სლიმ ფიტი"},
    {"name": "ტყავის ქამარი", "price": 45, "quantity": 20, "sku": "BT-004", "description": "შავი, ნატურალური ტყავი"},
    {"name": "სპორტული კედები Adidas", "price": 210, "quantity": 3, "sku": "SN-005", "description": "ზომები 40-45"},
    {"name": "შალის შარფი", "price": 38, "quantity": 8, "sku": "SC-006", "description": "ნაცრისფერი, 180 სმ"},
]

QUESTIONS = [
    ("price", "რა ღირს წითელი მაისური?"),
    ("availability", "თეთრი პერანგი M ზომაში გაქვთ?"),
    ("out_of_stock", "შავი ჯინსი მინდა, გაქვთ?"),
    ("order_intent", "მომწონს კედები, როგორ შევუკვეთო?"),
    ("handoff", "ოპერატორთან მინდა საუბარი, ადამიანი დამიკავშირდეს"),
    ("rude_offtopic", "შენ სულელი ხარ? მითხარი ამინდი რა იქნება ხვალ"),
    ("knowledge", "მიწოდება რა ღირს ქუთაისში და რამდენ დღეში მოვა?"),
    ("multi_product", "მაისური, ქამარი და შარფი რა ჯდება ერთად?"),
    ("greeting", "გამარჯობა"),
    ("english_russian", "Привет! Сколько стоят кеды Adidas? And do you deliver to Batumi?"),
]


def load_api_key() -> str:
    """GEMINI_API_KEY from the environment, else from the .env files (only that one line)."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    for path in (BACKEND / ".env", BACKEND.parent / ".env"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].lstrip()
            if line.startswith("GEMINI_API_KEY"):
                name, sep, value = line.partition("=")
                if sep and name.strip() == "GEMINI_API_KEY":
                    value = value.strip().strip("'\"")
                    if value:
                        return value
    return ""


def build_prompt() -> str:
    # Same builder as the bot; only the order link is pinned so Settings/.env is never loaded.
    bot.order_link_for = lambda shop: f"https://example.test/panel/order.html?shop={shop.get('id')}"
    relevant = bot.select_relevant_products(PRODUCTS, "")
    return bot.build_system_prompt(SHOP, relevant, total=len(PRODUCTS))


def safe(e: Exception, key: str) -> str:
    msg = str(e)
    if key:
        msg = msg.replace(key, "***")
    return f"{type(e).__name__}: {msg[:500]}"


def ask(client, types, model, system_prompt, question, key, delay):
    """One call with a single 429 retry. Returns a result dict (never raises, never leaks key)."""
    config = types.GenerateContentConfig(
        system_instruction=system_prompt, temperature=TEMPERATURE, max_output_tokens=MAX_OUTPUT_TOKENS
    )
    contents = [types.Content(role="user", parts=[types.Part(text=question)])]
    for attempt in range(2):
        t0 = time.monotonic()
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
            latency = time.monotonic() - t0
            um = getattr(resp, "usage_metadata", None)
            cand = (resp.candidates or [None])[0]
            fr = getattr(cand, "finish_reason", None)
            raw = (resp.text or "").strip()
            return {
                "text": raw,
                "latency": latency,
                "prompt": getattr(um, "prompt_token_count", None) or 0,
                "output": getattr(um, "candidates_token_count", None) or 0,
                "thinking": getattr(um, "thoughts_token_count", None) or 0,
                "finish": str(getattr(fr, "name", fr)),
                "handoff": bot.HANDOFF_TOKEN in raw,
                "error": None,
            }
        except Exception as e:  # noqa: BLE001
            err = safe(e, key)
            if attempt == 0 and ("429" in err or "RESOURCE_EXHAUSTED" in err):
                print(f"    429 on {model}, backing off {max(delay, 30):.0f}s and retrying once")
                time.sleep(max(delay, 30))
                continue
            return {"text": "", "latency": time.monotonic() - t0, "prompt": 0, "output": 0,
                    "thinking": 0, "finish": "ERROR", "handoff": False, "error": err}


def render(models, system_prompt, results) -> str:
    out = ["# Gemini model comparison", "",
           f"Models: {', '.join(models)}  ",
           f"temperature={TEMPERATURE}, max_output_tokens={MAX_OUTPUT_TOKENS}  ",
           f"System prompt length: {len(system_prompt)} chars", ""]
    for (qid, q), per_model in zip(QUESTIONS, results):
        out += [f"## {qid}", "", f"**Question:** {q}", ""]
        for m in models:
            r = per_model[m]
            out += [f"### {m}", ""]
            if r["error"]:
                out += [f"ERROR: {r['error']}", ""]
                continue
            out += [
                "```text", r["text"] or "(empty)", "```", "",
                f"- latency: {r['latency']:.1f}s; tokens prompt/output/thinking: "
                f"{r['prompt']}/{r['output']}/{r['thinking']}",
                f"- HANDOFF marker: {'yes' if r['handoff'] else 'no'}; finish_reason: {r['finish']}"
                + ("  **(CUT: MAX_TOKENS)**" if "MAX_TOKENS" in r["finish"] else ""),
                "",
            ]
    out += ["## Summary", "",
            "| model | prompt tok | output tok | thinking tok | avg latency s | HANDOFF count | cut (MAX_TOKENS) | errors |",
            "|---|---|---|---|---|---|---|---|"]
    for m in models:
        rs = [pm[m] for pm in results]
        n = len(rs) or 1
        out.append(
            f"| {m} | {sum(r['prompt'] for r in rs)} | {sum(r['output'] for r in rs)} | "
            f"{sum(r['thinking'] for r in rs)} | {sum(r['latency'] for r in rs) / n:.1f} | "
            f"{sum(r['handoff'] for r in rs)} | {sum('MAX_TOKENS' in r['finish'] for r in rs)} | "
            f"{sum(bool(r['error']) for r in rs)} |"
        )
    out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs=2, default=["gemini-2.5-flash", "gemini-3.5-flash"], metavar=("A", "B"))
    ap.add_argument("--delay", type=float, default=13.0, help="seconds between calls (free tier: 5 req/min)")
    ap.add_argument("--out", default=str(BACKEND / "scripts" / "compare_gemini_output.md"))
    ap.add_argument("--dry-run", action="store_true", help="no API call, no key/.env access")
    args = ap.parse_args()

    system_prompt = build_prompt()
    if args.dry_run:
        print(f"Models: {args.models}")
        print(f"System prompt length: {len(system_prompt)} chars")
        print(f"Calls planned: {len(QUESTIONS) * 2}; min time ~{len(QUESTIONS) * 2 * args.delay / 60:.1f} min")
        for qid, q in QUESTIONS:
            print(f"- [{qid}] {q}")
        return 0

    key = load_api_key()
    if not key:
        print("GEMINI_API_KEY not found in environment or .env files")
        return 2
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
    except Exception as e:  # noqa: BLE001
        print(safe(e, key))
        return 1

    results, first = [], True
    for qid, q in QUESTIONS:
        per_model = {}
        for m in args.models:
            if not first:
                time.sleep(args.delay)
            first = False
            print(f"[{qid}] {m} ...")
            per_model[m] = ask(client, types, m, system_prompt, q, key, args.delay)
            r = per_model[m]
            print(f"    {r['finish']} {r['latency']:.1f}s" + (f" ERROR {r['error']}" if r["error"] else ""))
        results.append(per_model)

    md = render(args.models, system_prompt, results)
    if key:
        md = md.replace(key, "***")
    Path(args.out).write_text(md, encoding="utf-8")
    print(f"Written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
