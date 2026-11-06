"""A-043 (N-06): ადმინის ცვლილებების კვალი — `admin_audit_log` (migration 0041).

Semantics: best-effort და მოქმედების **შემდეგ** (Decision Log 2026-11-06). ჯერ ცვლილება სრულდება, მერე იწერება
ჩანაწერი; ჩაწერის ჩავარდნა (ცხრილი არ არის, ბაზა მიუწვდომელია) ადმინის მოქმედებას არ აჩერებს — მხოლოდ WARNING
ლოგში. ეს მფლობელის მიერ მიღებული რისკია (PROJECT.md → Accepted Risks): ორ ჩანაწერს შორის ერთ transaction-ს
Supabase REST არ იძლევა, ხოლო ადმინის დაბლოკვა audit-ის გამო უარესია, ვიდრე ერთეული გამოტოვებული ჩანაწერი.
"""
import logging

TABLE = "admin_audit_log"

ACTIONS = frozenset({
    "shop.update",
    "shop.delete",
    "upgrade_request.approve",
    "upgrade_request.reject",
    "subscription.extend",
    "seller.recovery",
})

# allow-list: details-ში მხოლოდ id-ები, რიცხვები და ფლაგები — email / სახელი / token / ბმული აქ ვერ მოხვდება
DETAIL_KEYS = frozenset({
    "owner_id", "shop_id", "bot_enabled", "subscription_tier", "requested_tier",
    "tier", "days", "paid_until", "email_sent",
})

_MISSING_CODES = ("PGRST205", "42P01")  # ცხრილი არ არის (PostgREST schema cache / Postgres undefined_table)
_SCALARS = (str, int, float, bool, type(None))

logger = logging.getLogger("app")
_MISSING_WARNED = False


def record(sc, admin_id: str, action: str, target: str | None, details: dict | None = None) -> bool:
    """ჩაწერს ადმინის მოქმედებას. True — ჩაიწერა; False — ვერ ჩაიწერა (ლოგში WARNING).

    არასდროს აგდებს, გარდა `ValueError`-ისა: უცნობი action / details-ის უცნობი გასაღები ან არა-სკალარი
    მნიშვნელობა პროგრამისტის შეცდომაა და უნდა გამოჩნდეს ტესტში, არა production-ში ჩუმად.
    `None` მნიშვნელობები ამოიღება.
    """
    global _MISSING_WARNED
    if action not in ACTIONS:
        raise ValueError(f"unknown admin audit action: {action!r}")
    clean: dict = {}
    for key, value in (details or {}).items():
        if key not in DETAIL_KEYS:
            raise ValueError(f"admin audit detail key not allowed: {key!r}")
        if not isinstance(value, _SCALARS):
            raise ValueError(f"admin audit detail {key!r} must be a scalar, got {type(value).__name__}")
        if value is not None:
            clean[key] = value
    row = {
        "admin_id": admin_id,
        "action": action,
        "target": None if target is None else str(target)[:64],
        "details": clean,
    }
    try:
        sc.table(TABLE).insert(row).execute()
    except Exception as exc:
        if getattr(exc, "code", None) in _MISSING_CODES:
            if not _MISSING_WARNED:
                _MISSING_WARNED = True
                logger.warning(
                    "admin_audit_log missing (migration 0041 not applied) - admin actions are not audited"
                )
            return False
        logger.warning("admin audit write failed (%s, action=%s)", type(exc).__name__, action)
        return False
    return True


def _reset_for_tests() -> None:
    global _MISSING_WARNED
    _MISSING_WARNED = False
