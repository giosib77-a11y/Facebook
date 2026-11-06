"""Admin endpoints — SaaS მფლობელისთვის (ყველა მაღაზიის ხედვა).

წვდომა მხოლოდ ADMIN_USER_IDS-ში ჩაწერილ ანგარიშებს აქვს. მონაცემები service_role-ით
იკითხება (RLS-ს გვერდს უვლის), ამიტომ admin-შემოწმება კრიტიკულია.
"""
import logging
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.core.db import fetch_all
from app.core.ratelimit import _client_ip
from app.core.security import CurrentAuth, confirm_with_auth_server, get_current_auth
from app.core.supabase_client import get_service_client
from app.core.tiers import (
    TIER_LABELS,
    TIER_LIMITS,
    TIER_PRICES,
    best_tier,
    limits_for,
    normalize_tier,
)
from app.services import admin_audit, budget, notify, subscriptions
from app.services.bot_limits import enforce_bot_limit

PRODUCT_IMAGES_BUCKET = "product-images"  # იგივე, რაც api/products.py-ში

# A-041: ცხადი ჭერი; გადაჭარბება — WARNING (fetch_all), არა ჩუმი ჭრა
_ADMIN_SHOPS_MAX = 20_000      # shops / subscriptions და სხვა მცირე ცხრილები
_ADMIN_ORDERS_MAX = 200_000    # orders / products / bot_customers (მხოლოდ Python-ის fallback-ში)
_ADMIN_PRODUCTS_MAX = 10_000   # ერთი მაღაზიის პროდუქტები (shop_detail)

# 0039-ის RPC-ები (admin_overview_stats / admin_growth / admin_shop_counts) არ არის ბაზაში
_RPC_MISSING_CODES = ("PGRST202", "42883")
_RPC_WARNED: set[str] = set()  # ფუნქცია, რომლისთვისაც WARNING უკვე დაიწერა (ერთხელ პროცესზე)

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger("app")


class AdminShopUpdate(BaseModel):
    bot_enabled: bool | None = None
    subscription_tier: str | None = None


class AdminRecovery(BaseModel):
    # str_strip_whitespace: strip სიგრძის შემოწმებამდე, ამიტომ "   " → 422
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=3, max_length=320)


class ResolveRequest(BaseModel):
    approve: bool


class ExtendIn(BaseModel):
    days: int = Field(ge=1, le=366)


_warned_no_admins = False
_warned_no_mfa = False

# frontend ამ ზუსტ ტექსტს ადარებს (`frontend/src/lib/adminMfa.js` → ADMIN_MFA_REQUIRED) და MFA-ს ეკრანს
# „არა ადმინისგან" სწორედ ამით არჩევს — ტექსტი ორივე მხარეს ერთად იცვლება.
_MFA_REQUIRED = "ადმინ პანელისთვის საჭიროა ორფაქტორიანი შესვლა (MFA)"


def get_current_admin(auth: CurrentAuth = Depends(get_current_auth)) -> CurrentAuth:
    """ამოწმებს, რომ ავტორიზებული მომხმარებლის user_id ADMIN_USER_IDS-შია და (თუ მოთხოვნილია) token არის aal2.

    მაღალი პრივილეგია, დაბალი ტრაფიკი: ლოკალურად შემოწმებული token ყოველთვის მოწმდება Auth server-თანაც —
    sign-out / ban / წაშლა ადმინზე მაშინვე მოქმედებს. არა-ადმინი ქსელის გარეშე იჭრება (403).

    რიგი: (1) ADMIN_USER_IDS; (2) MFA (`aal` claim, ADMIN_REQUIRE_MFA); (3) Auth server-ით დადასტურება.
    MFA ქსელამდეა: შემოწმება ლოკალურია და იაფი, aal1 token Auth server-ს არ აწუხებს. `aal` ქსელურ გზაზეც
    სანდოა: ის იმავე token-ის წარმატებული `get_user`-ის შემდეგ იკითხება (claims მხოლოდ მაშინ, თუ `sub` ემთხვევა).
    """
    global _warned_no_admins, _warned_no_mfa
    settings = get_settings()
    admin_ids = settings.admin_user_id_set
    if not admin_ids and settings.is_production and not _warned_no_admins:
        _warned_no_admins = True
        logger.warning("ADMIN_USER_IDS is empty in production — admin panel is disabled")
    # getattr: test_auth_local_jwt.py-ის SimpleNamespace settings-ს ეს ველი არ აქვს (რეალურ Settings-ს ყოველთვის აქვს);
    # ველის გარეშე იგივე default, რაც Settings-ში: production -> ჩართული (fail closed), dev -> გამორთული
    mfa_required = getattr(settings, "admin_mfa_required", settings.is_production)
    if not mfa_required and settings.is_production and not _warned_no_mfa:
        _warned_no_mfa = True
        logger.warning("ADMIN_REQUIRE_MFA is off in production - admin MFA (aal2) is not enforced")
    if (auth.user_id or "").strip().lower() not in admin_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "წვდომა მხოლოდ ადმინისთვის")
    if mfa_required and (auth.claims or {}).get("aal") != "aal2":
        raise HTTPException(status.HTTP_403_FORBIDDEN, _MFA_REQUIRED)
    if auth.verified_by == "local":
        confirm_with_auth_server(auth)
    return auth


def _parse_ts(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def _all_auth_users(sc) -> list:
    """ყველა Auth-მომხმარებელი, გვერდ-გვერდ.

    `list_users()` default-ად მხოლოდ ერთ გვერდს (~50) აბრუნებს — 50+ მომხმარებელზე
    ზოგი „გამოცურდებოდა". აქ გვერდებს ბოლომდე ვკითხულობთ (ჭერით — უსასრულო ციკლის დაზღვევა).
    """
    out: list = []
    per_page = 200
    for page in range(1, 51):  # ჭერი ~10000 მომხმარებელი
        try:
            res = sc.auth.admin.list_users(page=page, per_page=per_page)
        except TypeError:
            # ძველი gotrue — page/per_page არ იღებს → რასაც აბრუნებს, იმას ავიღებთ
            try:
                res = sc.auth.admin.list_users()
                out.extend(list(getattr(res, "users", res) or []))
            except Exception:
                pass
            break
        except Exception:
            break
        batch = list(getattr(res, "users", res) or [])
        if not batch:
            break  # ცარიელ გვერდზე ვჩერდებით — per_page-ს სერვერი შეიძლება ჩუმად შეზღუდოს,
                   # ამიტომ „< per_page"-ს არ ვენდობით (თორემ ზოგი მომხმარებელი გამოგვრჩება)
        out.extend(batch)
    return out


def _email_map(sc) -> dict:
    """user_id -> email (Supabase Auth admin API-დან)."""
    out = {}
    for u in _all_auth_users(sc):
        uid = getattr(u, "id", None)
        if uid:
            out[str(uid)] = getattr(u, "email", None)
    return out


def _restore_bots(sc, owner_id: str, tier: str) -> int:
    """პაკეტის აწევისას — ბოტს ვუბრუნებთ იმ მაღაზიებს, სადაც downgrade-მა გათიშა.

    ⚠️ რევიუ P1-6-ის მეორე ნახევარი. `downgrade-free` ლიმიტს ზემოთ მყოფ მაღაზიებზე
    `bot_enabled=False`-ს სვამს. თუ აქ არ დავაბრუნებდით, გადახდის შემდეგაც ბოტი
    გამორთული დარჩებოდა და გამყიდველს თვითონ ვერ ჩაერთო (seller-ის PATCH მხოლოდ
    bot_language-ს იღებს) — ე.ი. ხვრელის ნაცვლად ხაფანგს მივიღებდით.

    ვრთავთ მხოლოდ დაკავშირებულ გვერდებს (facebook_page_id არსებობს) და მხოლოდ
    ახალი პაკეტის ჭერამდე. შენიშვნა: თუ ადმინმა გვერდი განზრახ „მოკლა"
    (kill-switch), აქ ის გაცოცხლდება — იშვიათია და ხელახლა გამორთვა ერთი დაწკაპია.
    """
    limit = TIER_LIMITS[normalize_tier(tier)]["shops"]
    rows = (
        sc.table("shops").select("id,created_at,bot_enabled,facebook_page_id")
        .eq("owner_id", owner_id).execute().data or []
    )
    candidates = [r for r in rows if r.get("facebook_page_id") and not r.get("bot_enabled")]
    if not candidates:
        return 0
    if limit is not None:
        # უკვე ჩართულები იკავებენ ადგილს — დანარჩენს ჭერამდე ვავსებთ
        active = len([r for r in rows if r.get("bot_enabled")])
        free_slots = max(0, limit - active)
        candidates = sorted(candidates, key=lambda r: str(r.get("created_at") or ""))[:free_slots]
    if not candidates:
        return 0
    sc.table("shops").update({"bot_enabled": True}).in_(
        "id", [r["id"] for r in candidates]
    ).execute()
    return len(candidates)


def _apply_bot_limit(sc, owner_id: str, tier: str) -> None:
    """პაკეტის შეცვლის შემდეგ ბოტებს ახალ ჭერს ვუთანხმებთ: ზედმეტი ითიშება, ადგილი თუ გაჩნდა — ბრუნდება.

    enforce ჯერ (downgrade), restore მერე (upgrade): ორივე იდემპოტენტურია, ერთმანეთს არ ეწინააღმდეგება.
    შეცდომა → 500: tier უკვე შეცვლილია, ადმინმა იგივე მოქმედება უნდა გაიმეოროს.
    """
    try:
        enforce_bot_limit(sc, owner_id)
        _restore_bots(sc, owner_id, tier)
    except Exception:
        logger.exception("ბოტების ჭერის გამოყენება ვერ მოხერხდა (owner=%s)", owner_id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "პაკეტი შეიცვალა, მაგრამ ბოტების ჭერის გამოყენება ვერ მოხერხდა — გაიმეორე მოქმედება.",
        )


@router.get("/check")
def check(admin: CurrentAuth = Depends(get_current_admin)):
    """მსუბუქი შემოწმება — ადმინია თუ არა (frontend ამით აჩენს „ადმინი" ღილაკს)."""
    return {"is_admin": True}


@router.get("/client-ip")
def client_ip(request: Request, admin: CurrentAuth = Depends(get_current_admin)):
    """დიაგნოსტიკა — proxy-ის IP header-ები და რას ხედავს rate limiter. მხოლოდ ეს ველები."""
    h = request.headers
    return {
        "x_forwarded_for": h.get("x-forwarded-for"),
        "cf_connecting_ip": h.get("cf-connecting-ip"),
        "true_client_ip": h.get("true-client-ip"),
        "x_real_ip": h.get("x-real-ip"),
        # untrusted: uvicorn proxy-headers ამას X-Forwarded-For-ით ანაცვლებს (გაყალბებადია)
        "peer_untrusted": request.client.host if request.client else None,
        "resolved": _client_ip(request),
        "client_ip_trusted_hops": get_settings().client_ip_trusted_hops,
    }


def _admin_rpc(sc, fn: str, params: dict | None = None) -> dict | None:
    """ადმინის SQL-აგრეგაცია (migration 0039): dict, ან None → გამომძახებელი Python-ის გზაზე გადადის.

    RPC ყოველ მოთხოვნაზე ისევ ცდება (flag მხოლოდ WARNING-ს აჩუმებს) — migration-ის შემდეგ restart არ სჭირდება.
    ფუნქცია არ არის (PGRST202 / 42883) → None + ერთი WARNING პროცესზე ფუნქციაზე; სხვა შეცდომა ადის (500).
    """
    try:
        data = sc.rpc(fn, params or {}).execute().data
    except Exception as exc:
        if getattr(exc, "code", None) not in _RPC_MISSING_CODES:
            raise
        if fn not in _RPC_WARNED:
            _RPC_WARNED.add(fn)
            logger.warning("%s missing (migration 0039 not applied) - Python aggregation", fn)
        return None
    return data if isinstance(data, dict) else None


def _overview_python(sc) -> dict:
    """0039-ის გარეშე: იგივე რიცხვები Python-ში, გვერდ-გვერდ (fetch_all) — ნელია, მაგრამ სწორი."""
    shops = fetch_all(
        lambda: sc.table("shops").select("id,owner_id,facebook_page_id,subscription_tier").order("id"),
        max_rows=_ADMIN_SHOPS_MAX, label="admin overview shops",
    )
    orders = fetch_all(
        lambda: sc.table("orders").select("total,status,created_at").order("id"),
        max_rows=_ADMIN_ORDERS_MAX, label="admin overview orders",
    )
    products = sc.table("products").select("id", count="exact").limit(1).execute()

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    orders_30d, revenue = 0, 0.0
    for o in orders:
        if o.get("status") != "cancelled":
            revenue += float(o.get("total") or 0)
        ts = _parse_ts(o.get("created_at"))
        if ts and ts >= cutoff:
            orders_30d += 1

    owner_tiers: dict[str, list] = {}
    for s in shops:
        oid = s.get("owner_id")
        if oid:
            owner_tiers.setdefault(str(oid), []).append(s.get("subscription_tier"))
    return {
        "total_shops": len(shops),
        "total_sellers": len({s["owner_id"] for s in shops if s.get("owner_id")}),
        "connected_shops": len([s for s in shops if s.get("facebook_page_id")]),
        "total_products": products.count or 0,
        "total_orders": len(orders),
        "orders_30d": orders_30d,
        "revenue": revenue,
        "owner_tiers": dict(Counter(best_tier(t) for t in owner_tiers.values())),
    }


@router.get("/overview")
def overview(admin: CurrentAuth = Depends(get_current_admin)):
    """საერთო მაჩვენებლები — მთელი პლატფორმა."""
    sc = get_service_client()
    stats = _admin_rpc(sc, "admin_overview_stats")
    if stats is None:
        stats = _overview_python(sc)

    # MRR + პაკეტების განაწილება — გამოწერა per-account-ია (ერთი გადახდა ფარავს
    # მფლობელის ყველა მაღაზიას), ამიტომ მფლობელობით ვთვლით, არა მაღაზიაზე —
    # თორემ მრავალ-მაღაზიიანი მფლობელი MRR-ს ხელოვნურად ბერავს.
    # `owner_tiers` = {პაკეტი: მფლობელების რაოდენობა} (SQL-იდან ან Python-იდან); ფასი — TIER_PRICES (ერთი წყარო).
    mrr = 0
    tier_counts = {"free": 0, "basic": 0, "standard": 0, "business": 0}
    for tier, n in (stats.get("owner_tiers") or {}).items():
        t, n = normalize_tier(tier), int(n or 0)
        tier_counts[t] = tier_counts.get(t, 0) + n
        mrr += TIER_PRICES.get(t, 0) * n

    # API Contract: alert = kill_switch or (today_usd >= 80% of the daily cap) — spend_status already folds both in
    llm = budget.spend_status(sc)

    return {
        "total_shops": int(stats.get("total_shops") or 0),
        "total_sellers": int(stats.get("total_sellers") or 0),
        "connected_shops": int(stats.get("connected_shops") or 0),
        "total_products": int(stats.get("total_products") or 0),
        "total_orders": int(stats.get("total_orders") or 0),
        "orders_30d": int(stats.get("orders_30d") or 0),
        "revenue": round(float(stats.get("revenue") or 0), 2),
        "mrr": mrr,
        "tier_counts": tier_counts,
        "llm": llm,
    }


def _last_months(n: int) -> list[str]:
    """ბოლო n თვის 'YYYY-MM' სია (ძველიდან ახლისკენ)."""
    now = datetime.now(timezone.utc)
    y, m = now.year, now.month
    out = []
    for i in range(n):
        yy, mm = y, m - i
        while mm <= 0:
            mm += 12
            yy -= 1
        out.append(f"{yy:04d}-{mm:02d}")
    return list(reversed(out))


@router.get("/growth")
def growth(admin: CurrentAuth = Depends(get_current_admin), months: int = 6):
    """ბოლო N თვის ზრდა — ახალი მაღაზიები + შეკვეთები თვეობრივად."""
    months = max(1, min(months, 24))
    sc = get_service_client()
    yms = _last_months(months)
    data = _admin_rpc(sc, "admin_growth", {"p_months": months})
    if data is not None:
        # SQL მხოლოდ მონაცემიან თვეებს აბრუნებს — ნულებს აქ ვავსებთ; _last_months-ს გარეთა გასაღებები იგნორდება
        def _n(ym: str, key: str) -> int:
            row = data.get(ym)
            return int((row.get(key) if isinstance(row, dict) else 0) or 0)

        return [{"ym": ym, "shops": _n(ym, "shops"), "orders": _n(ym, "orders")} for ym in yms]

    shops = fetch_all(
        lambda: sc.table("shops").select("created_at,id").order("id"),
        max_rows=_ADMIN_SHOPS_MAX, label="admin growth shops",
    )
    orders = fetch_all(
        lambda: sc.table("orders").select("created_at,id").order("id"),
        max_rows=_ADMIN_ORDERS_MAX, label="admin growth orders",
    )
    sh = {ym: 0 for ym in yms}
    od = {ym: 0 for ym in yms}
    for s in shops:
        ym = str(s.get("created_at"))[:7]
        if ym in sh:
            sh[ym] += 1
    for o in orders:
        ym = str(o.get("created_at"))[:7]
        if ym in od:
            od[ym] += 1
    return [{"ym": ym, "shops": sh[ym], "orders": od[ym]} for ym in yms]


@router.get("/shops")
def all_shops(admin: CurrentAuth = Depends(get_current_admin)):
    """ყველა მაღაზიის სია — მფლობელი, აქტივობა, სტატუსი."""
    sc = get_service_client()
    shops = fetch_all(
        lambda: sc.table("shops").select("*").order("created_at", desc=True).order("id"),
        max_rows=_ADMIN_SHOPS_MAX, label="admin shops",
    )
    emails = _email_map(sc)

    try:
        sub_rows = fetch_all(
            lambda: sc.table("subscriptions").select("owner_id,paid_until").order("owner_id"),
            max_rows=_ADMIN_SHOPS_MAX, label="admin subscriptions",
        )
        paid_until_by_owner = {str(r["owner_id"]): r.get("paid_until") for r in sub_rows}
    except Exception:
        paid_until_by_owner = {}  # migration 0034 ჯერ არ გაშვებულა

    prod_count, order_count, cust_count = {}, {}, {}
    counts = _admin_rpc(sc, "admin_shop_counts")
    if counts is not None:
        # SQL-ში დათვლილი (1000-იანი ჭერის გარეშე); RPC-ში არმყოფი მაღაზია → 0
        for sid, c in counts.items():
            if isinstance(c, dict):
                prod_count[sid] = int(c.get("products") or 0)
                order_count[sid] = int(c.get("orders") or 0)
                cust_count[sid] = int(c.get("customers") or 0)
    else:
        products = fetch_all(
            lambda: sc.table("products").select("shop_id").order("id"),
            max_rows=_ADMIN_ORDERS_MAX, label="admin shops products",
        )
        orders = fetch_all(
            lambda: sc.table("orders").select("shop_id").order("id"),
            max_rows=_ADMIN_ORDERS_MAX, label="admin shops orders",
        )
        ym = datetime.now(timezone.utc).strftime("%Y-%m")
        try:
            cust_rows = fetch_all(
                lambda: sc.table("bot_customers").select("shop_id").eq("ym", ym).order("shop_id").order("psid"),
                max_rows=_ADMIN_ORDERS_MAX, label="admin shops customers",
            )
        except Exception:
            cust_rows = []  # migration ჯერ არ გაშვებულა
        for p in products:
            prod_count[p["shop_id"]] = prod_count.get(p["shop_id"], 0) + 1
        for o in orders:
            order_count[o["shop_id"]] = order_count.get(o["shop_id"], 0) + 1
        for c in cust_rows:
            cust_count[c["shop_id"]] = cust_count.get(c["shop_id"], 0) + 1

    result = []
    for s in shops:
        tier = normalize_tier(s.get("subscription_tier"))
        result.append({
            "id": s["id"],
            "name": s.get("name"),
            "owner_id": str(s["owner_id"]) if s.get("owner_id") else None,
            "paid_until": paid_until_by_owner.get(str(s.get("owner_id"))),
            "owner_email": emails.get(str(s.get("owner_id"))),
            "created_at": s.get("created_at"),
            "products": prod_count.get(s["id"], 0),
            "orders": order_count.get(s["id"], 0),
            "fb_connected": bool(s.get("facebook_page_id")),
            "bot_enabled": bool(s.get("bot_enabled")),
            "tier": tier,
            "tier_label": TIER_LABELS[tier],
            "monthly_customers": cust_count.get(s["id"], 0),
            "customer_limit": limits_for(tier)["customers"],
        })
    return result


@router.get("/sellers")
def all_sellers(admin: CurrentAuth = Depends(get_current_admin)):
    """ყველა რეგისტრირებული მომხმარებელი — email, დადასტურება, ბოლო შესვლა, მაღაზიები."""
    sc = get_service_client()
    shops = fetch_all(
        lambda: sc.table("shops").select("owner_id").order("id"),
        max_rows=_ADMIN_SHOPS_MAX, label="admin sellers shops",
    )
    shop_count: dict = {}
    for s in shops:
        oid = str(s.get("owner_id"))
        shop_count[oid] = shop_count.get(oid, 0) + 1

    out = []
    for u in _all_auth_users(sc):
        uid = str(getattr(u, "id", ""))
        out.append({
            "id": uid,
            "email": getattr(u, "email", None),
            "confirmed": bool(getattr(u, "email_confirmed_at", None) or getattr(u, "confirmed_at", None)),
            "last_sign_in": getattr(u, "last_sign_in_at", None),
            "created_at": getattr(u, "created_at", None),
            "shops": shop_count.get(uid, 0),
        })
    return out


@router.get("/orders")
def recent_orders(admin: CurrentAuth = Depends(get_current_admin), limit: int = 50):
    """ბოლო შეკვეთები ყველა მაღაზიიდან."""
    sc = get_service_client()
    limit = max(1, min(limit, 200))
    orders = (
        sc.table("orders").select("*").order("created_at", desc=True).limit(limit).execute().data or []
    )
    # მხოლოდ ამ ≤200 შეკვეთის მაღაზიები (არა მთელი ცხრილი — 1000-იანი ჭერი სახელებს გამოტოვებდა)
    shop_ids = sorted({o["shop_id"] for o in orders if o.get("shop_id")})
    shops = (
        sc.table("shops").select("id,name").in_("id", shop_ids).execute().data or [] if shop_ids else []
    )
    name_map = {s["id"]: s.get("name") for s in shops}
    for o in orders:
        o["shop_name"] = name_map.get(o.get("shop_id"))
    return orders


@router.get("/shops/{shop_id}")
def shop_detail(shop_id: str, admin: CurrentAuth = Depends(get_current_admin)):
    """ერთი მაღაზიის დეტალები — პროდუქტები + ბოლო შეკვეთები."""
    sc = get_service_client()
    shop = sc.table("shops").select("*").eq("id", shop_id).limit(1).execute().data
    if not shop:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა")
    products = fetch_all(
        lambda: sc.table("products").select("*").eq("shop_id", shop_id).order("name").order("id"),
        max_rows=_ADMIN_PRODUCTS_MAX, label="admin shop products",
    )
    orders = (
        sc.table("orders").select("*").eq("shop_id", shop_id)
        .order("created_at", desc=True).limit(20).execute().data or []
    )
    s = shop[0]
    s.pop("facebook_page_token", None)  # ტოკენს არ ვაბრუნებთ
    s.pop("knowledge", None)
    return {"shop": s, "products": products, "orders": orders}


@router.patch("/shops/{shop_id}")
def update_shop(shop_id: str, payload: AdminShopUpdate, admin: CurrentAuth = Depends(get_current_admin)):
    """ბოტის ჩართვა/გამორთვა (kill-switch — per-shop) ან პაკეტის შეცვლა (per-account)."""
    if payload.bot_enabled is None and payload.subscription_tier is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "განსაახლებელი ველი არ არის")
    if payload.subscription_tier is not None and payload.subscription_tier not in TIER_LABELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "არასწორი პაკეტი")

    sc = get_service_client()
    shop = sc.table("shops").select("owner_id").eq("id", shop_id).limit(1).execute().data
    if not shop:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა")
    owner_id = shop[0].get("owner_id")

    # bot_enabled — per-shop (ერთი გვერდის kill-switch)
    if payload.bot_enabled is not None:
        sc.table("shops").update({"bot_enabled": payload.bot_enabled}).eq("id", shop_id).execute()

    # subscription_tier — per-account (გამოწერა მფლობელზეა → ყველა მისი მაღაზია,
    # approve/downgrade-ის მსგავსად; თორემ შერეული ტარიფები გაჩნდება)
    if payload.subscription_tier is not None:
        q = sc.table("shops").update({"subscription_tier": payload.subscription_tier})
        (q.eq("owner_id", owner_id) if owner_id else q.eq("id", shop_id)).execute()
        if owner_id:
            # ადმინის ხელით ცვლა: მოქმედი ფასიანი ვადა უცვლელია, ახალი ფასიანი → +30 დღე, free → ვადის გარეშე
            subscriptions.apply_tier(sc, owner_id, payload.subscription_tier, renewal=False)
            _apply_bot_limit(sc, owner_id, payload.subscription_tier)

    details = {"owner_id": owner_id}
    if payload.bot_enabled is not None:
        details["bot_enabled"] = payload.bot_enabled
    if payload.subscription_tier is not None:
        details["subscription_tier"] = payload.subscription_tier
    admin_audit.record(sc, admin.user_id, "shop.update", shop_id, details)

    res =sc.table("shops").select("*").eq("id", shop_id).limit(1).execute().data
    row = dict(res[0]) if res else {}
    row.pop("facebook_page_token", None)  # ტოკენს/ცოდნას პასუხში არ ვაბრუნებთ
    row.pop("knowledge", None)
    return row


@router.delete("/shops/{shop_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shop(shop_id: str, admin: CurrentAuth = Depends(get_current_admin)):
    """მაღაზიის სრული წაშლა (პროდუქტები + შეკვეთები + მაღაზია + Storage-ის ფოტოები)."""
    sc = get_service_client()
    exists = sc.table("shops").select("id,owner_id").eq("id", shop_id).limit(1).execute().data
    if not exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა")
    sc.table("orders").delete().eq("shop_id", shop_id).execute()
    sc.table("products").delete().eq("shop_id", shop_id).execute()
    sc.table("shops").delete().eq("id", shop_id).execute()
    admin_audit.record(sc, admin.user_id, "shop.delete", shop_id, {"owner_id": exists[0].get("owner_id")})
    _remove_shop_images(sc, shop_id)
    return None


def _remove_shop_images(sc, shop_id: str) -> None:
    """Best-effort: product-images/{shop_id}/* წაშლა. შეცდომა მხოლოდ ლოგდება."""
    try:
        bucket = sc.storage.from_(PRODUCT_IMAGES_BUCKET)
        for _ in range(50):  # ზედა ზღვარი — უსასრულო ციკლის წინააღმდეგ
            objects = bucket.list(shop_id, {"limit": 100}) or []
            paths = [f"{shop_id}/{o['name']}" for o in objects if o.get("name")]
            if not paths:
                break
            bucket.remove(paths)
    except Exception:
        logger.warning("shop image cleanup failed for shop %s", shop_id)


@router.get("/upgrade-requests")
def list_upgrade_requests(admin: CurrentAuth = Depends(get_current_admin)):
    """მიმდინარე (pending) პაკეტის განახლების მოთხოვნები."""
    sc = get_service_client()
    try:
        reqs = (
            sc.table("upgrade_requests").select("*").eq("status", "pending")
            .order("created_at", desc=True).execute().data or []
        )
    except Exception:
        return []  # migration 0005 ჯერ არ გაშვებულა
    shop_ids = sorted({r["shop_id"] for r in reqs if r.get("shop_id")})
    shops = (
        sc.table("shops").select("id,name,subscription_tier,owner_id").in_("id", shop_ids).execute().data or []
        if shop_ids else []
    )
    smap = {s["id"]: s for s in shops}
    emails = _email_map(sc)
    for r in reqs:
        s = smap.get(r.get("shop_id")) or {}
        r["shop_name"] = s.get("name")
        r["current_tier"] = normalize_tier(s.get("subscription_tier"))
        r["owner_email"] = emails.get(str(s.get("owner_id")))
        r["tier_label"] = TIER_LABELS.get(r.get("requested_tier"), r.get("requested_tier"))
    return reqs


@router.post("/upgrade-requests/{req_id}/resolve")
def resolve_upgrade_request(
    req_id: str, payload: ResolveRequest, admin: CurrentAuth = Depends(get_current_admin)
):
    """მოთხოვნის დადასტურება (პაკეტს ცვლის) ან უარყოფა."""
    sc = get_service_client()
    req = sc.table("upgrade_requests").select("*").eq("id", req_id).limit(1).execute().data
    if not req:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მოთხოვნა ვერ მოიძებნა")
    r = req[0]
    # მხოლოდ pending მოთხოვნა მუშავდება — დამუშავებულის ხელახლა approve პაკეტს აღარ ცვლის
    if r.get("status") != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "მოთხოვნა უკვე დამუშავებულია")
    now_iso = datetime.now(timezone.utc).isoformat()
    if payload.approve:
        tier = r["requested_tier"]
        if tier not in TIER_LABELS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "არასწორი პაკეტი")
        # per-account: მფლობელის ყველა მაღაზია გადადის ამ პაკეტზე (ერთი გამოწერა — ყველა მაღაზია)
        owner = sc.table("shops").select("owner_id").eq("id", r["shop_id"]).limit(1).execute().data
        if owner:
            oid = owner[0]["owner_id"]
            # ვადა ჯერ (renewal: იგივე tier + მოქმედი ვადა → +30 დღე); ჩავარდნა approve-ს არ აჩერებს
            subscriptions.apply_tier(sc, oid, tier, renewal=True)
            sc.table("shops").update({"subscription_tier": tier}).eq("owner_id", oid).execute()
            # გადახდა დადასტურდა → downgrade-ით გათიშული ბოტები ბრუნდება (P1-6)
            _apply_bot_limit(sc, oid, tier)
        else:
            sc.table("shops").update({"subscription_tier": tier}).eq("id", r["shop_id"]).execute()
        (
            sc.table("upgrade_requests").update({"status": "approved", "resolved_at": now_iso})
            .eq("id", req_id).eq("status", "pending").execute()
        )
    else:
        (
            sc.table("upgrade_requests").update({"status": "rejected", "resolved_at": now_iso})
            .eq("id", req_id).eq("status", "pending").execute()
        )
    action = "upgrade_request.approve" if payload.approve else "upgrade_request.reject"
    admin_audit.record(
        sc, admin.user_id, action, req_id,
        {"shop_id": r.get("shop_id"), "requested_tier": r.get("requested_tier")},
    )
    return {"ok": True}


@router.post("/subscriptions/{owner_id}/extend")
def extend_subscription(
    owner_id: uuid.UUID, payload: ExtendIn, admin: CurrentAuth = Depends(get_current_admin)
):
    """ფასიანი გამოწერის ვადის გაგრძელება N დღით: `max(ახლა, არსებული paid_until) + days`."""
    sc = get_service_client()
    oid = str(owner_id)
    shops = sc.table("shops").select("subscription_tier").eq("owner_id", oid).execute().data or []
    if not shops:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მფლობელი ვერ მოიძებნა")
    tier = best_tier(s.get("subscription_tier") for s in shops)
    if tier == "free":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "უფასო პაკეტს ვადა არ აქვს")

    unavailable = HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, "გამოწერების ცხრილი ჯერ არ არის (migration 0034)"
    )
    try:
        current = subscriptions.read(sc, oid, strict=True)
    except Exception:
        raise unavailable
    now = datetime.now(timezone.utc)
    current_until = subscriptions.parse_ts((current or {}).get("paid_until"))
    base = max(now, current_until) if current_until else now
    paid_until = base + timedelta(days=payload.days)
    if not subscriptions.write(sc, oid, tier, paid_until):
        raise unavailable
    admin_audit.record(
        sc, admin.user_id, "subscription.extend", oid,
        {"tier": tier, "days": payload.days, "paid_until": paid_until.isoformat()},
    )
    return {"owner_id": oid, "tier": tier, "paid_until": paid_until.isoformat()}


@router.post("/recovery")
def seller_recovery(payload: AdminRecovery, admin: CurrentAuth = Depends(get_current_admin)):
    """გამყიდვლისთვის პაროლის აღდგენის ბმულის გაგზავნა (მხარდაჭერისთვის).

    ბმული პასუხში **არ** ბრუნდება — ის მხოლოდ გამყიდვლის ფოსტაზე იგზავნება. რატომ: მოპარული ადმინის
    ანგარიში არ უნდა იძლეოდეს ნებისმიერი გამყიდველის ანგარიშის დაკავების საშუალებას; ბმული მხოლოდ
    ანგარიშის მფლობელის ფოსტაში უნდა მოხვდეს. SMTP-ის გარეშე ბმულს საერთოდ არ ვქმნით (503).
    ბმული / email ლოგში არასდროს იწერება; exception-ზე — მხოლოდ კლასის სახელი.
    """
    settings = get_settings()
    if not settings.email_notifications_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ელფოსტა არ არის კონფიგურირებული (SMTP) — აღდგენის ბმული ვერ გაიგზავნება",
        )
    email = payload.email
    params: dict = {"type": "recovery", "email": email}
    base = (settings.public_base_url or "").strip()
    if base:
        params["options"] = {"redirect_to": f"{base.rstrip('/')}/panel/reset.html"}
    sc = get_service_client()
    try:
        link = sc.auth.admin.generate_link(params)
        props = getattr(link, "properties", None)
        action_link = getattr(props, "action_link", None) if props else None
        if not action_link:
            raise ValueError("empty action_link")
        user = getattr(link, "user", None)
        target = getattr(user, "id", None) if user else None
    except Exception as exc:
        logger.warning("recovery link generation failed (%s)", type(exc).__name__)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ბმულის გენერაცია ვერ მოხერხდა")
    body = (
        "გამარჯობა,\n\n"
        "მხარდაჭერის მოთხოვნით შეიქმნა ChatAssist-ის პაროლის აღდგენის ბმული:\n\n"
        f"{action_link}\n\n"
        "ბმული ერთჯერადია და მალე იწურება; თუ ეს თქვენ არ მოგითხოვიათ — უგულებელყავით წერილი.\n"
    )
    sent = notify.send_email(email, "ChatAssist — პაროლის აღდგენა", body)
    admin_audit.record(sc, admin.user_id, "seller.recovery", target, {"email_sent": sent})
    if not sent:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "ბმული შეიქმნა, მაგრამ ელფოსტა ვერ გაიგზავნა — სცადე ხელახლა",
        )
    return {"ok": True}
