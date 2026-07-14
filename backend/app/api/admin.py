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

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminShopUpdate(BaseModel):
    bot_enabled: bool


class AdminRecovery(BaseModel):
    email: str


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


def _email_map(sc) -> dict:
    """user_id -> email (Supabase Auth admin API-დან)."""
    out = {}
    try:
        res = sc.auth.admin.list_users()
        users = getattr(res, "users", res)  # ვერსიის მიხედვით list ან .users
        for u in users:
            uid = getattr(u, "id", None)
            if uid:
                out[str(uid)] = getattr(u, "email", None)
    except Exception:
        pass
    return out


@router.get("/check")
def check(admin: CurrentAuth = Depends(get_current_admin)):
    """მსუბუქი შემოწმება — ადმინია თუ არა (frontend ამით აჩენს „ადმინი" ღილაკს)."""
    return {"is_admin": True}


@router.get("/overview")
def overview(admin: CurrentAuth = Depends(get_current_admin)):
    """საერთო მაჩვენებლები — მთელი პლატფორმა."""
    sc = get_service_client()
    shops = sc.table("shops").select("id,owner_id,facebook_page_id").execute().data or []
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

    return {
        "total_shops": len(shops),
        "total_sellers": len({s["owner_id"] for s in shops if s.get("owner_id")}),
        "connected_shops": len([s for s in shops if s.get("facebook_page_id")]),
        "total_products": products.count or 0,
        "total_orders": len(orders),
        "orders_30d": orders_30d,
        "revenue": round(revenue, 2),
    }


@router.get("/shops")
def all_shops(admin: CurrentAuth = Depends(get_current_admin)):
    """ყველა მაღაზიის სია — მფლობელი, აქტივობა, სტატუსი."""
    sc = get_service_client()
    shops = sc.table("shops").select("*").order("created_at", desc=True).execute().data or []
    products = sc.table("products").select("shop_id").execute().data or []
    orders = sc.table("orders").select("shop_id").execute().data or []
    emails = _email_map(sc)

    prod_count, order_count = {}, {}
    for p in products:
        prod_count[p["shop_id"]] = prod_count.get(p["shop_id"], 0) + 1
    for o in orders:
        order_count[o["shop_id"]] = order_count.get(o["shop_id"], 0) + 1

    return [
        {
            "id": s["id"],
            "name": s.get("name"),
            "owner_email": emails.get(str(s.get("owner_id"))),
            "created_at": s.get("created_at"),
            "products": prod_count.get(s["id"], 0),
            "orders": order_count.get(s["id"], 0),
            "fb_connected": bool(s.get("facebook_page_id")),
            "bot_enabled": bool(s.get("bot_enabled")),
        }
        for s in shops
    ]


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
    try:
        res = sc.auth.admin.list_users()
        users = getattr(res, "users", res)
        for u in users:
            uid = str(getattr(u, "id", ""))
            out.append({
                "id": uid,
                "email": getattr(u, "email", None),
                "confirmed": bool(getattr(u, "email_confirmed_at", None) or getattr(u, "confirmed_at", None)),
                "last_sign_in": getattr(u, "last_sign_in_at", None),
                "created_at": getattr(u, "created_at", None),
                "shops": shop_count.get(uid, 0),
            })
    except Exception:
        pass
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
    """ბოტის ჩართვა/გამორთვა (admin kill-switch)."""
    sc = get_service_client()
    res = sc.table("shops").update({"bot_enabled": payload.bot_enabled}).eq("id", shop_id).execute()
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა")
    return res.data[0]


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
