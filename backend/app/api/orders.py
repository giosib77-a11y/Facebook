"""Orders endpoints — საჯარო შესაკვეთი ფორმა + გამყიდველის შეკვეთების მართვა."""
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError

from app.core.db import run
from app.core.ratelimit import rate_limit
from app.core.security import CurrentAuth, get_current_auth
from app.core.supabase_client import get_service_client
from app.models.order import OrderCreate, OrderOut, OrderStatusUpdate

router = APIRouter(tags=["orders"])


def _decrement_stock_atomic(sc, shop_id: str, req_items: list) -> bool | None:
    """ატომური მარაგის დაკლება migration 0009-ის RPC-ით.

    აბრუნებს:
      True  — დაიკლო წარმატებით (race-safe)
      None  — RPC ჯერ არ არსებობს (migration 0009 არ გაშვებულა) → legacy fallback
    არასაკმარის მარაგზე/არარსებულ პროდუქტზე → HTTPException 400.
    """
    try:
        sc.rpc("decrement_stock", {"p_shop_id": shop_id, "p_items": req_items}).execute()
        return True
    except APIError as e:
        msg = getattr(e, "message", None) or str(e)
        code = getattr(e, "code", None)
        m = re.search(r"INSUFFICIENT_STOCK\|(.*?)\|(\d+)", msg)
        if m:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"„{m.group(1)}“ — მარაგში მხოლოდ {m.group(2)} ცალია",
            )
        if "PRODUCT_NOT_FOUND" in msg:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "პროდუქტი ვერ მოიძებნა მაღაზიაში")
        if "INVALID_QTY" in msg:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "რაოდენობა არასწორია")
        # ფუნქცია ჯერ არ არსებობს → legacy გზაზე გადავდივართ
        if code in ("42883", "PGRST202") or "does not exist" in msg or "Could not find" in msg:
            return None
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "მარაგის განახლება ვერ მოხერხდა")


def _apply_stock_delta(sc, shop_id: str, items: list, sign: int) -> None:
    """მარაგის კორექცია: sign=-1 (შეკვეთა, გამოკლება) ან +1 (გაუქმება, დაბრუნება).
    იკითხება მიმდინარე quantity და ინახება ახალი (floor 0-ზე)."""
    agg: dict[str, int] = {}
    for it in items:
        pid = it.get("product_id")
        if pid:
            agg[pid] = agg.get(pid, 0) + int(it.get("quantity", 0))
    if not agg:
        return
    rows = (
        sc.table("products")
        .select("id,quantity")
        .eq("shop_id", str(shop_id))
        .in_("id", list(agg.keys()))
        .execute()
        .data
    )
    for r in rows:
        new_q = int(r["quantity"]) + sign * agg[r["id"]]
        if new_q < 0:
            new_q = 0
        sc.table("products").update({"quantity": new_q}).eq("id", r["id"]).execute()


# ---------- საჯარო (კლიენტი, ავტორიზაციის გარეშე) ----------
@router.get("/public-menu", dependencies=[Depends(rate_limit("public_menu", limit=60, window=60))])
def public_menu(shop_id: uuid.UUID):
    """მაღაზიის სახელი + აქტიური პროდუქტები — შესაკვეთი ფორმისთვის."""
    sc = get_service_client()
    shop = sc.table("shops").select("id,name,currency").eq("id", str(shop_id)).limit(1).execute()
    if not shop.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა")
    products = (
        sc.table("products")
        .select("id,name,price,quantity,description")
        .eq("shop_id", str(shop_id))
        .eq("is_active", True)
        .order("name")
        .execute()
        .data
    )
    return {"shop": shop.data[0], "products": products}


@router.post(
    "/orders",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("create_order", limit=10, window=60))],
)
def create_order(payload: OrderCreate):
    """კლიენტი ქმნის შეკვეთას (საჯარო). ჩაწერა service_role-ით."""
    sc = get_service_client()
    shop = sc.table("shops").select("id").eq("id", str(payload.shop_id)).limit(1).execute()
    if not shop.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა")

    # ფასი/სახელი ბაზიდან — არა კლიენტისგან (მანიპულაციის თავიდან ასაცილებლად).
    product_ids = [str(i.product_id) for i in payload.items if i.product_id]
    if not product_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "შეკვეთა ცარიელია")
    db_products = (
        sc.table("products")
        .select("id,name,price,quantity")
        .eq("shop_id", str(payload.shop_id))
        .in_("id", product_ids)
        .execute()
        .data
    )
    price_map = {p["id"]: p for p in db_products}

    # ფასი/სახელი ბაზიდან; მარაგის შემოწმებას ატომური RPC აკეთებს (ქვემოთ).
    items, req_items, total = [], [], 0.0
    for i in payload.items:
        pid = str(i.product_id) if i.product_id else None
        prod = price_map.get(pid)
        if not prod:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"პროდუქტი ვერ მოიძებნა მაღაზიაში: {i.name}"
            )
        price = float(prod["price"])
        items.append(
            {"product_id": pid, "name": prod["name"], "price": price, "quantity": i.quantity}
        )
        req_items.append({"product_id": pid, "quantity": i.quantity})
        total += price * i.quantity
    total = round(total, 2)

    # ── მარაგის ატომური დაკლება (race-safe) ──────────────────────────────────
    # atomic=True → RPC-მ დააკლო; None → RPC არ არსებობს → legacy გზა (არა-ატომური).
    atomic = _decrement_stock_atomic(sc, str(payload.shop_id), req_items)
    if atomic is None:
        for i in payload.items:
            prod = price_map.get(str(i.product_id) if i.product_id else None)
            if prod and i.quantity > int(prod["quantity"]):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"„{prod['name']}“ — მარაგში მხოლოდ {int(prod['quantity'])} ცალია "
                    f"(ითხოვე {i.quantity})",
                )
        _apply_stock_delta(sc, str(payload.shop_id), items, -1)

    row = {
        "shop_id": str(payload.shop_id),
        "customer_name": payload.customer_name.strip(),
        "customer_phone": (payload.customer_phone or "").strip() or None,
        "customer_address": (payload.customer_address or "").strip() or None,
        "note": (payload.note or "").strip() or None,
        "items": items,
        "total": total,
        "status": "new",
    }
    res = sc.table("orders").insert(row).execute()
    if not res.data:
        # შეკვეთა ვერ ჩაიწერა — მარაგი უკან დავაბრუნოთ (თუ უკვე დავაკელით)
        if atomic:
            _apply_stock_delta(sc, str(payload.shop_id), items, +1)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "შეკვეთის შექმნა ვერ მოხერხდა")

    return {"ok": True, "order_id": res.data[0]["id"], "total": total}


# ---------- გამყიდველი (ავტორიზებული) ----------
@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    auth: CurrentAuth = Depends(get_current_auth),
    status_filter: str | None = Query(default=None, alias="status"),
):
    """მიმდინარე გამყიდველის შეკვეთები (RLS-ით მხოლოდ მისი მაღაზიების)."""
    query = auth.client.table("orders").select("*").order("created_at", desc=True)
    if status_filter:
        query = query.eq("status", status_filter)
    return run(query).data


@router.patch("/orders/{order_id}", response_model=OrderOut)
def update_order_status(
    order_id: uuid.UUID,
    payload: OrderStatusUpdate,
    auth: CurrentAuth = Depends(get_current_auth),
):
    """შეკვეთის სტატ უსის შეცვლა (RLS-ით მხოლოდ საკუთარი).
    გაუქმებაზე მარაგი უკან ბრუნდება; გაუქმებულის ხელახლა გახსნაზე — ისევ აკლდება."""
    # მიმდინარე მდგომარეობა (RLS ადასტურებს მფლობელობას)
    cur = run(
        auth.client.table("orders")
        .select("status,items,shop_id")
        .eq("id", str(order_id))
        .limit(1)
    )
    if not cur.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "შეკვეთა ვერ მოიძებნა ან არ არის თქვენი")
    old_status = cur.data[0]["status"]
    items = cur.data[0].get("items") or []
    shop_id = cur.data[0]["shop_id"]
    new_status = payload.status

    res = run(
        auth.client.table("orders").update({"status": new_status}).eq("id", str(order_id))
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "შეკვეთა ვერ მოიძებნა ან არ არის თქვენი")

    # მარაგის კორექცია სტატ უსის ცვლილებაზე
    if new_status == "cancelled" and old_status != "cancelled":
        _apply_stock_delta(get_service_client(), shop_id, items, +1)  # დაბრუნება
    elif old_status == "cancelled" and new_status != "cancelled":
        _apply_stock_delta(get_service_client(), shop_id, items, -1)  # ისევ გამოკლება

    return res.data[0]


@router.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(
    order_id: uuid.UUID,
    auth: CurrentAuth = Depends(get_current_auth),
):
    """შეკვეთის წაშლა სიიდან (RLS-ით მხოლოდ საკუთარი).
    მარაგს არ ცვლის — მიწოდებული ნივთი გაყიდულია. მარაგის დასაბრუნებლად
    გამოიყენე „გაუქმებული“ სტატ უსი."""
    res = run(auth.client.table("orders").delete().eq("id", str(order_id)))
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "შეკვეთა ვერ მოიძებნა ან არ არის თქვენი")
    return None
