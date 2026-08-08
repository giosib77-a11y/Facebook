"""Admin endpoints — SaaS მფლობელისთვის (ყველა მაღაზიის ხედვა).

წვდომა მხოლოდ ADMIN_EMAIL-ის მქონე ანგარიშს აქვს. მონაცემები service_role-ით
იკითხება (RLS-ს გვერდს უვლის), ამიტომ admin-შემოწმება კრიტიკულია.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import get_settings
from app.core.security import CurrentAuth, get_current_auth
from app.core.supabase_client import get_service_client
from app.core.tiers import TIER_LABELS, TIER_PRICES, best_tier, limits_for, normalize_tier

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminShopUpdate(BaseModel):
    bot_enabled: bool | None = None
    subscription_tier: str | None = None


class AdminRecovery(BaseModel):
    email: str


class ResolveRequest(BaseModel):
    approve: bool


def get_current_admin(auth: CurrentAuth = Depends(get_current_auth)) -> CurrentAuth:
    """ამოწმებს, რომ ავტორიზებული მომხმარებელი ADMIN_EMAIL-ია."""
    admin_email = (get_settings().admin_email or "").strip().lower()
    if not admin_email or (auth.email or "").strip().lower() != admin_email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "წვდომა მხოლოდ ადმინისთვის")
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


@router.get("/check")
def check(admin: CurrentAuth = Depends(get_current_admin)):
    """მსუბუქი შემოწმება — ადმინია თუ არა (frontend ამით აჩენს „ადმინი" ღილაკს)."""
    return {"is_admin": True}


@router.get("/overview")
def overview(admin: CurrentAuth = Depends(get_current_admin)):
    """საერთო მაჩვენებლები — მთელი პლატფორმა."""
    sc = get_service_client()
    shops = sc.table("shops").select("id,owner_id,facebook_page_id,subscription_tier").execute().data or []
    orders = sc.table("orders").select("total,status,created_at").execute().data or []
    products = sc.table("products").select("id", count="exact").limit(1).execute()

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    orders_30d, revenue = 0, 0.0
    for o in orders:
        if o.get("status") != "cancelled":
            revenue += float(o.get("total") or 0)
        ts = _parse_ts(o.get("created_at"))
        if ts and ts >= cutoff:
            orders_30d += 1

    # MRR + პაკეტების განაწილება — გამოწერა per-account-ია (ერთი გადახდა ფარავს
    # მფლობელის ყველა მაღაზიას), ამიტომ მფლობელობით ვთვლით, არა მაღაზიაზე —
    # თორემ მრავალ-მაღაზიიანი მფლობელი MRR-ს ხელოვნურად ბერავს.
    owner_tiers: dict[str, list] = {}
    for s in shops:
        oid = s.get("owner_id")
        if oid:
            owner_tiers.setdefault(str(oid), []).append(s.get("subscription_tier"))
    mrr = 0
    tier_counts = {"free": 0, "basic": 0, "standard": 0, "business": 0}
    for tiers in owner_tiers.values():
        t = best_tier(tiers)
        tier_counts[t] = tier_counts.get(t, 0) + 1
        mrr += TIER_PRICES.get(t, 0)

    return {
        "total_shops": len(shops),
        "total_sellers": len({s["owner_id"] for s in shops if s.get("owner_id")}),
        "connected_shops": len([s for s in shops if s.get("facebook_page_id")]),
        "total_products": products.count or 0,
        "total_orders": len(orders),
        "orders_30d": orders_30d,
        "revenue": round(revenue, 2),
        "mrr": mrr,
        "tier_counts": tier_counts,
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
    shops = sc.table("shops").select("created_at").execute().data or []
    orders = sc.table("orders").select("created_at").execute().data or []
    yms = _last_months(months)
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
    shops = sc.table("shops").select("*").order("created_at", desc=True).execute().data or []
    products = sc.table("products").select("shop_id").execute().data or []
    orders = sc.table("orders").select("shop_id").execute().data or []
    emails = _email_map(sc)

    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        cust_rows = sc.table("bot_customers").select("shop_id").eq("ym", ym).execute().data or []
    except Exception:
        cust_rows = []  # migration ჯერ არ გაშვებულა

    prod_count, order_count, cust_count = {}, {}, {}
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
    shops = sc.table("shops").select("owner_id").execute().data or []
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
    shops = sc.table("shops").select("id,name").execute().data or []
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
    products = sc.table("products").select("*").eq("shop_id", shop_id).order("name").execute().data or []
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

    res = sc.table("shops").select("*").eq("id", shop_id).limit(1).execute().data
    row = dict(res[0]) if res else {}
    row.pop("facebook_page_token", None)  # ტოკენს/ცოდნას პასუხში არ ვაბრუნებთ
    row.pop("knowledge", None)
    return row


@router.delete("/shops/{shop_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shop(shop_id: str, admin: CurrentAuth = Depends(get_current_admin)):
    """მაღაზიის სრული წაშლა (პროდუქტები + შეკვეთები + მაღაზია)."""
    sc = get_service_client()
    exists = sc.table("shops").select("id").eq("id", shop_id).limit(1).execute().data
    if not exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა")
    sc.table("orders").delete().eq("shop_id", shop_id).execute()
    sc.table("products").delete().eq("shop_id", shop_id).execute()
    sc.table("shops").delete().eq("id", shop_id).execute()
    return None


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
    shops = sc.table("shops").select("id,name,subscription_tier,owner_id").execute().data or []
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
    now_iso = datetime.now(timezone.utc).isoformat()
    if payload.approve:
        tier = r["requested_tier"]
        if tier not in TIER_LABELS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "არასწორი პაკეტი")
        # per-account: მფლობელის ყველა მაღაზია გადადის ამ პაკეტზე (ერთი გამოწერა — ყველა მაღაზია)
        owner = sc.table("shops").select("owner_id").eq("id", r["shop_id"]).limit(1).execute().data
        if owner:
            sc.table("shops").update({"subscription_tier": tier}).eq("owner_id", owner[0]["owner_id"]).execute()
        else:
            sc.table("shops").update({"subscription_tier": tier}).eq("id", r["shop_id"]).execute()
        sc.table("upgrade_requests").update({"status": "approved", "resolved_at": now_iso}).eq("id", req_id).execute()
    else:
        sc.table("upgrade_requests").update({"status": "rejected", "resolved_at": now_iso}).eq("id", req_id).execute()
    return {"ok": True}


@router.post("/recovery")
def seller_recovery(payload: AdminRecovery, admin: CurrentAuth = Depends(get_current_admin)):
    """გამყიდვლისთვის პაროლის აღდგენის ბმულის გენერაცია (მხარდაჭერისთვის)."""
    sc = get_service_client()
    try:
        link = sc.auth.admin.generate_link({"type": "recovery", "email": payload.email})
        props = getattr(link, "properties", None)
        action_link = getattr(props, "action_link", None) if props else None
        return {"ok": True, "action_link": action_link}
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ბმულის გენერაცია ვერ მოხერხდა: {e}")
