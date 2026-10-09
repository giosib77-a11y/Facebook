"""ბოტების რაოდენობის ჭერი პაკეტის მიხედვით (per-account).

ერთი წყარო სამი გზისთვის: გამყიდველის downgrade-free, ადმინის tier-ის ცვლა და
upgrade-request-ის დადასტურება. სამივე ჯერ `subscription_tier`-ს წერს და მერე ამას იძახებს —
webhook მხოლოდ `bot_enabled`-ს ამოწმებს, ამიტომ ჭერი ამ დროშით უნდა დაცული იყოს.
"""
import logging

from app.core.tiers import owner_shop_limit

logger = logging.getLogger("app.bot_limits")


def enforce_bot_limit(sc, owner_id: str) -> list[dict]:
    """მფლობელის ჩართულ ბოტებს ჭერამდე ამცირებს; აბრუნებს გათიშულ მაღაზიებს ({id, name}).

    ჭერი = მფლობელის უმაღლესი პაკეტი (`owner_shop_limit`). რჩება **უკვე ჩართული**
    ბოტებიდან ყველაზე ძველი `limit` — გამორთული მაღაზია ადგილს არ იკავებს.
    იდემპოტენტურია. DB-ის შეცდომას არ ყლაპავს (გამომძახებელი წყვეტს რა ქნას).
    """
    rows = (
        sc.table("shops").select("id,name,created_at,bot_enabled,subscription_tier")
        .eq("owner_id", owner_id).execute().data or []
    )
    limit = owner_shop_limit([r.get("subscription_tier") for r in rows])
    if limit is None:
        return []
    enabled = sorted(
        (r for r in rows if r.get("bot_enabled")), key=lambda r: str(r.get("created_at") or "")
    )
    excess = enabled[limit:]
    if not excess:
        return []
    (
        sc.table("shops").update({"bot_enabled": False})
        .eq("owner_id", owner_id).in_("id", [r["id"] for r in excess]).execute()
    )
    logger.info("ბოტი გაითიშა %d მაღაზიაზე (owner=%s)", len(excess), owner_id)
    return [{"id": r["id"], "name": r.get("name")} for r in excess]
