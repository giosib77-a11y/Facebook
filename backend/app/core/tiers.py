"""გამოწერის პაკეტები და ლიმიტები (მონეტიზაცია).

customers = უნიკალური Messenger-კლიენტი თვეში (მთავარი ლიმიტი).
products  = მაქს. პროდუქტი მაღაზიაზე. None = ულიმიტო.
shops     = მაქს. მაღაზია/გვერდი მფლობელზე (მისი უმაღლესი პაკეტით). None = ულიმიტო.
"""

TIER_LIMITS = {
    "free":     {"customers": 30,   "products": 20,   "shops": 1},
    "basic":    {"customers": 200,  "products": 150,  "shops": 1},
    "standard": {"customers": 800,  "products": 1000, "shops": 2},
    "business": {"customers": 3000, "products": None, "shops": None},
}

# პაკეტის რიგი (დაბლიდან მაღლა) — უმაღლესი პაკეტის დასათვლელად
TIER_ORDER = ["free", "basic", "standard", "business"]

# რომელ პაკეტებს აქვთ Excel/CSV + PDF ატვირთვა (bulk import / ბოტის ცოდნა)
BULK_IMPORT_TIERS = {"basic", "standard", "business"}

TIER_LABELS = {
    "free": "უფასო",
    "basic": "საბაზისო",
    "standard": "სტანდარტი",
    "business": "ბიზნესი",
}

# ფასი თვეში (₾)
TIER_PRICES = {
    "free": 0,
    "basic": 29,
    "standard": 69,
    "business": 149,
}

# ერთი კლიენტის მაქს. შეტყობინება დღეში (abuse/loop დაცვა) — ყველა პაკეტში
DAILY_ABUSE_CAP = 100


def normalize_tier(tier: str | None) -> str:
    return tier if tier in TIER_LIMITS else "free"


def limits_for(tier: str | None) -> dict:
    return TIER_LIMITS[normalize_tier(tier)]


def bulk_import_allowed(tier: str | None) -> bool:
    """Excel/CSV/PDF ატვირთვა ხელმისაწვდომია თუ არა ამ პაკეტზე."""
    return normalize_tier(tier) in BULK_IMPORT_TIERS


def best_tier(tiers) -> str:
    """მოცემული პაკეტებიდან უმაღლესი (მფლობელს რამდენიმე მაღაზია შეიძლება ჰქონდეს)."""
    best = "free"
    for t in tiers:
        nt = normalize_tier(t)
        if TIER_ORDER.index(nt) > TIER_ORDER.index(best):
            best = nt
    return best


def owner_shop_limit(tiers) -> int | None:
    """მფლობელის მაღაზიების ჭერი — მისი უმაღლესი პაკეტის მიხედვით. None = ულიმიტო."""
    return TIER_LIMITS[best_tier(tiers)]["shops"]
