"""გამოწერის პაკეტები და ლიმიტები (მონეტიზაცია).

customers = უნიკალური Messenger-კლიენტი თვეში (მთავარი ლიმიტი).
products  = მაქს. პროდუქტი მაღაზიაზე. None = ულიმიტო.
"""

TIER_LIMITS = {
    "free":     {"customers": 30,   "products": 20},
    "basic":    {"customers": 200,  "products": 150},
    "standard": {"customers": 800,  "products": 1000},
    "business": {"customers": 3000, "products": None},
}

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
