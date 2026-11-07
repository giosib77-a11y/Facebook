"""Stage 22 (A-041): ბოტის `search_products` tool-ის ძებნა დიდ კატალოგზე — Postgres-ში (RPC 0040).

პატარა კატალოგზე ძებნა მეხსიერებაშია (`prompt.match_products`); `bot_db_search_min_products`-დან
(default 300; `0` = არასდროს) ან მეტ პროდუქტზე — RPC `search_products`, რომელიც 5 000-იანი ჭერის
მიღმაც სრულ კატალოგს ეძებს. ტოკენები იგივე `prompt.query_tokens`-ია, ქულა — იგივე წესი, რაც
`match_products`-ში (რამდენი ტოკენი ემთხვევა name / description / sku / image_description-ს).

Tenant isolation: `shop_id` მხოლოდ გამომძახებლისგან (`ToolContext.shop`) მოდის, არასდროს LLM-ის
არგუმენტიდან; ფილტრი `p_shop` თავად RPC-შია. service client — სესია არ არის (webhook-ის ბოტი).

RPC-ის ნებისმიერი შეცდომა (ფუნქციის არარსებობაც): `None` → გამომძახებელი მეხსიერების ძებნაზე გადადის
(Stage 22-ის resilience; კატალოგი ≤5 000 პროდუქტით უკვე ჩატვირთულია), WARNING — არაუმეტეს 60 წამში ერთხელ;
backoff არ არის: მომდევნო ძახილი RPC-ს მაშინვე ისევ ცდის.
ლოგში query / ტოკენები / პროდუქტი არასდროს ხვდება.
"""
import logging
import time

from app.config import get_settings
from app.core.supabase_client import get_service_client
from app.services import prompt

logger = logging.getLogger("app.product_search")

RPC = "search_products"
_TERMS_MAX = 8
_TERM_MAX_CHARS = 50
_QUERY_MAX_CHARS = 200
_ERROR_WARN_INTERVAL_SECONDS = 60.0

_error_warned_at: float | None = None


def _now() -> float:
    return time.monotonic()


def enabled_for(n_products: int) -> bool:
    """მეხსიერების ნაცვლად Postgres-ში ვეძებთ? `0` = გამორთულია."""
    threshold = get_settings().bot_db_search_min_products
    return 0 < threshold <= n_products


def search(shop_id: str, query: str, limit: int) -> list[dict] | None:
    """მაღაზიის აქტიური პროდუქტები, საუკეთესო პირველი; `None` = RPC მიუწვდომელია → მეხსიერების ძებნა.

    ცარიელი სია = ძებნა შესრულდა და არაფერია (ან query-ში მხოლოდ stopword-ებია — RPC არ იძახება).
    """
    global _error_warned_at
    terms = sorted(t for t in prompt.query_tokens(query) if len(t) <= _TERM_MAX_CHARS)[:_TERMS_MAX]
    if not terms:
        return []
    now = _now()
    try:
        data = get_service_client().rpc(RPC, {
            "p_shop": shop_id,
            "p_terms": terms,
            "p_query": query[:_QUERY_MAX_CHARS],
            "p_limit": limit,
        }).execute().data
    except Exception as exc:  # noqa: BLE001 — ძებნის შეცდომამ ბოტის პასუხი არ უნდა გააფუჭოს
        if _error_warned_at is None or now - _error_warned_at >= _ERROR_WARN_INTERVAL_SECONDS:
            _error_warned_at = now
            logger.warning("search_products RPC failed (%s) - in-memory search", type(exc).__name__)
        return None
    if not isinstance(data, list):
        return None
    return [row for row in data if isinstance(row, dict)]


def _reset_for_tests() -> None:
    global _error_warned_at
    _error_warned_at = None
