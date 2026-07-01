"""Orders endpoints — საჯარო შესაკვეთი ფორმა + გამყიდველის შეკვეთების მართვა."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.db import run
from app.core.security import CurrentAuth, get_current_auth
from app.core.supabase_client import get_service_client
from app.models.order import OrderCreate, OrderOut, OrderStatusUpdate

router = APIRouter(tags=["orders"])


# ---------- საჯარო (კლიენტი, ავტორიზაციის გარეშე) ----------
@router.get("/public-menu")
def public_menu(shop_id: uuid.UUID):
    """მაღაზიის სახ ელი + აქტიური პროდუქტები — შესაკვეთი ფორმისთვის."""
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


@router.post("/orders", status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate):
    """კლიენტი ქმნის შეკვეთას (საჯარო). ჩაწერა service_role-ით."""
    sc = get_service_client()
    shop = sc.table("shops").select("id").eq("id", str(payload.shop_id)).limit(1).execute()
    if not shop.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა")

    # ფასი/სახ ელი ბაზიდან — არა კლიენტისგან (მანიპულაციის თავიდან ასაცილებლად).
    product_ids = [str(i.product_id) for i in payload.items if i.product_id]
    if not product_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "შეკვეთა ცარიელია")
    db_products = (
        sc.table("products")
        .select("id,name,price")
        .eq("shop_id", str(payload.shop_id))
        .in_("id", product_ids)
        .execute()
        .data
    )
    price_map = {p["id"]: p for p in db_products}

    items, total = [], 0.0
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
        total += price * i.quantity
    total = round(total, 2)

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
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "შეკვეთის შექმნა ვერ მოხერხდა")
    return {"ok": True, "order_id": res.data[0]["id"], "total": total}


# ---------- გამყიდველი (ავტორიზებული) ----------
@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    auth: CurrentAuth = Depends(get_current_auth),
    status_filter: str | None = Query(default=None, alias="status"),
):
    """მიმდინარე გამყიდველის შეკვეთები (RLS-ით მხ ოლოდ მისი მაღაზიების)."""
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
    """შეკვეთის სტატ უსის შეცვლა (RLS-ით მხ ოლოდ საკუთარი)."""
    res = run(
        auth.client.table("orders").update({"status": payload.status}).eq("id", str(order_id))
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "შეკვეთა ვერ მოიძებნა ან არ არის თქვენი")
    return res.data[0]
