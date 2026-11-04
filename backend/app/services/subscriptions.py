"""გამოწერის ვადა (A-036 / N-02): `subscriptions (owner_id, tier, paid_until)` — migration 0034.

წყარო ვადისთვის — `subscriptions`; tier-ის runtime-წამკითხველები კვლავ `shops.subscription_tier`
სარკეს კითხულობენ (ის admin.py / shops.py-ში იწერება როგორც აქამდე). ვადაგასულს დღიური
pg_cron (`expire_subscriptions()`) `free`-ზე აბრუნებს.

migration 0034-ის გარეშე: წაკითხვა → None, ჩაწერა → False (ერთი WARNING პროცესზე / თითო ჩაწერაზე),
გამყიდველის და ადმინის ძველი ქცევა უცვლელია.
"""
import logging
from datetime import datetime, timedelta, timezone

PAID_PERIOD_DAYS = 30
EXPIRY_WARNING_DAYS = 3

logger = logging.getLogger("app")

_READ_WARNED = False  # "ცხრილი არ არის" WARNING — ერთხელ პროცესზე


def parse_ts(value) -> datetime | None:
    """ISO სტრიქონი / datetime → timezone-aware UTC datetime; ცუდი მნიშვნელობა → None."""
    if not value:
        return None
    if isinstance(value, datetime):
        ts = value
    else:
        try:
            ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def next_paid_until(current: dict | None, tier: str, *, renewal: bool, now: datetime) -> datetime | None:
    """ახალი `paid_until` პაკეტის ჩაწერისას (სუფთა ფუნქცია).

    - free → None;
    - `renewal` (approve), იგივე tier და მოქმედი ვადა → `current + 30 დღე` (ვადა არ იკარგება);
    - `renewal=False` (ადმინის ხელით ცვლა) და მოქმედი ფასიანი ვადა → უცვლელი;
    - სხვა შემთხვევა (ახალი / ვადაგასული / სხვა tier approve-ზე) → `now + 30 დღე`.
    """
    if tier == "free":
        return None
    period = timedelta(days=PAID_PERIOD_DAYS)
    cur_tier = (current or {}).get("tier")
    cur_until = parse_ts((current or {}).get("paid_until"))
    active = bool(cur_tier) and cur_tier != "free" and cur_until is not None and cur_until > now
    if active and renewal and cur_tier == tier:
        return cur_until + period
    if active and not renewal:
        return cur_until
    return now + period


def read(client, owner_id: str, *, strict: bool = False) -> dict | None:
    """მფლობელის `{tier, paid_until}` მწკრივი; არ არის → None.

    შეცდომა (ცხრილი არ არის / RLS / ქსელი) → None + ერთი WARNING პროცესზე; `strict=True` — შეცდომას აგდებს
    (extend-ისთვის: წაკითხვის ჩავარდნაზე არსებულ ვადას არ ვაქვეითებთ).
    """
    global _READ_WARNED
    try:
        rows = (
            client.table("subscriptions").select("tier,paid_until")
            .eq("owner_id", str(owner_id)).limit(1).execute().data
        )
    except Exception:
        if not _READ_WARNED:
            _READ_WARNED = True
            logger.warning("subscriptions table unavailable (migration 0034 not applied?) - expiry disabled")
        if strict:
            raise
        return None
    return dict(rows[0]) if rows else None


def write(sc, owner_id: str, tier: str, paid_until: datetime | None) -> bool:
    """upsert `subscriptions`-ში (service_role). შეცდომა → WARNING (მფლობელი + კლასი) → False."""
    row = {
        "owner_id": str(owner_id),
        "tier": tier,
        "paid_until": paid_until.isoformat() if paid_until else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        sc.table("subscriptions").upsert(row).execute()
    except Exception as e:
        logger.warning("subscriptions write failed (owner=%s): %s", owner_id, type(e).__name__)
        return False
    return True


def apply_tier(sc, owner_id: str, tier: str, *, renewal: bool) -> datetime | None:
    """tier-ის ცვლილებას ვადას უწერს (`next_paid_until`). ჩაწერის ჩავარდნა გამომძახებელს არ აჩერებს."""
    paid_until = next_paid_until(read(sc, owner_id), tier, renewal=renewal, now=datetime.now(timezone.utc))
    write(sc, owner_id, tier, paid_until)
    return paid_until


def status_for(tier: str, paid_until, now: datetime) -> dict:
    """usage-ის ველები: `paid_until` (ISO UTC | None), `expires_soon` (≤3 დღე დარჩა), `expired` (cron-მდე)."""
    until = parse_ts(paid_until) if tier != "free" else None
    if until is None:
        return {"paid_until": None, "expires_soon": False, "expired": False}
    return {
        "paid_until": until.isoformat(),
        "expires_soon": now < until <= now + timedelta(days=EXPIRY_WARNING_DAYS),
        "expired": until <= now,
    }
