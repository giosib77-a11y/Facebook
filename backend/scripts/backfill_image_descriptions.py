"""Backfill of products.image_description (Stage 18, S18-7) for products whose photo has no description.

For every candidate - a product with an empty description and a photo in this shop's own Storage
folder (product-images/<shop_id>/...) - the photo is described once (vision.describe_product_image)
and saved (vision.save_image_description). Products that already have a description are never
touched, so a second run only picks up what is left. Runs with the service client (no user session).

Run (OWNER ONLY, real API calls and cost; needs the key of LLM_PROVIDER and the 0028 migration),
from backend/:
    .venv/Scripts/python.exe -m scripts.backfill_image_descriptions [--dry-run] [--limit N]
                                                                    [--shop UUID] [--delay S]

Recommended: --dry-run, then a small --limit, then the rest. Exit codes: 0 done (failed photos are
counted, not fatal), 1 query error, 2 bad arguments / missing key / migration 0028 not applied,
130 interrupted. Only product ids and totals are printed: never names, URLs or descriptions.

Agents never run this script - tests import it with fakes.
"""
import argparse
import sys
import time
import uuid

from app.config import get_settings
from app.core.supabase_client import get_service_client
from app.services import facebook, vision
from scripts.compare_providers import PRICES

DEFAULT_LIMIT = 20
MAX_LIMIT = 500
DEFAULT_DELAY = 1.0
MAX_DELAY = 60.0
EST_INPUT_TOKENS = 2000  # per photo (image tokens + the prompt), a rough figure
EST_OUTPUT_TOKENS = vision.DESCRIBE_MAX_TOKENS
_MISSING_CODES = frozenset({"PGRST204", "42703"})


def _limit(value: str) -> int:
    n = int(value)
    if not 1 <= n <= MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"must be 1..{MAX_LIMIT}")
    return n


def _delay(value: str) -> float:
    x = float(value)
    if not 0 <= x <= MAX_DELAY:
        raise argparse.ArgumentTypeError(f"must be 0..{MAX_DELAY:g}")
    return x


def _shop_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError("must be a valid UUID") from None


def is_candidate(row: dict) -> bool:
    """Empty description + a photo in the product's own shop folder of this project's Storage."""
    if not isinstance(row, dict) or not row.get("id") or not row.get("shop_id"):
        return False
    if str(row.get("image_description") or "").strip():
        return False
    url = row.get("image_url")
    if not isinstance(url, str) or not facebook.is_own_storage_image_url(url):
        return False
    tail = url.partition(f"/{facebook.PRODUCT_IMAGES_BUCKET}/")[2]
    return tail.startswith(f"{row['shop_id']}/")


def estimate_usd(provider: str, n: int) -> float:
    pr = PRICES[provider]
    return n * (EST_INPUT_TOKENS * pr["input"] + EST_OUTPUT_TOKENS * pr["output"]) / 1e6


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="backfill_image_descriptions", description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=_limit, default=DEFAULT_LIMIT)
    ap.add_argument("--shop", type=_shop_uuid, default=None)
    ap.add_argument("--delay", type=_delay, default=DEFAULT_DELAY)
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:  # argparse exits with 2 on bad arguments (0 never reaches here without --help)
        return int(exc.code or 0)

    s = get_settings()
    if not args.dry_run and not s.llm_ready:
        print(f"error: {s.llm_key_env_name} is not set", file=sys.stderr)
        return 2

    sc = get_service_client()
    try:
        query = sc.table("products").select("id,shop_id,image_url,image_description")
        if args.shop:
            query = query.eq("shop_id", args.shop)
        rows = query.order("id").execute().data or []
    except Exception as exc:
        message = getattr(exc, "message", None) or str(exc)
        if getattr(exc, "code", None) in _MISSING_CODES and "image_description" in str(message):
            print("error: products.image_description is missing - run migration 0028 first",
                  file=sys.stderr)
            return 2
        print(f"error: products query failed ({type(exc).__name__})", file=sys.stderr)
        return 1

    candidates = [r for r in rows if is_candidate(r)]
    batch = candidates[: args.limit]
    cost = estimate_usd(s.llm_provider, len(batch))
    print(f"candidates: {len(candidates)} in total, {len(batch)} in this run")
    print(f"estimate: {len(batch)} x ~{EST_INPUT_TOKENS} input + <={EST_OUTPUT_TOKENS} output tokens "
          f"= ~${cost:.4f} ({s.llm_provider}, estimate from list prices)")

    if args.dry_run:
        for row in batch:
            print(f"would describe: {row['id']}")
        return 0

    ok = failed = 0
    try:
        for i, row in enumerate(batch):
            if i and args.delay > 0:
                time.sleep(args.delay)
            desc = vision.describe_product_image(row["shop_id"], row["image_url"])
            if desc and vision.save_image_description(
                    sc, row["id"], row["shop_id"], row["image_url"], desc):
                ok += 1
            else:
                failed += 1
                print(f"failed: {row['id']}")
    except KeyboardInterrupt:
        print(f"interrupted: {ok} saved, {failed} failed")
        return 130
    print(f"done: {ok} saved, {failed} failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
