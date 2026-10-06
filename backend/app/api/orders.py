"""Orders endpoints — საჯარო შესაკვეთი ფორმა + გამყიდველის შეკვეთების მართვა."""
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError

from app.core.db import run
from app.core.ratelimit import rate_limit
from app.core.security import CurrentAuth, get_current_auth
from app.core.supabase_client import get_service_client
from app.models.order import OrderCreate, OrderOut, OrderStatusUpdate

router = APIRouter(tags=["orders"])
logger = logging.getLogger("app")

# საჯარო შეკვეთის ბოროტად გამოყენების ლიმიტები (F-03B).
MAX_ITEM_QTY = 10  # ერთი პროდუქტის მაქს. ცალი ერთ შეკვეთაში (ჯამი product_id-ით)
SHOP_ORDERS_PER_HOUR = 30  # მაღაზიის საჯარო შეკვეთები მცოცავ საათში
# ბოტების დაცვა (FA-04).
MIN_FORM_MS = 3000  # ფორმის შევსების მინ. დრო (ms) გვერდის ჩატვირთვიდან
OPEN_ORDERS_PER_PHONE = 3  # ერთი ნომრის დაუდასტურებელი ("new") შეკვეთები 24 სთ-ში
_PHONE_CHARS = re.compile(r"[0-9 +\-()]+")
_NON_DIGITS = re.compile(r"[^0-9]")

# წაშლა მხოლოდ დასრულებულ სტატუსებზე (F-07): აქტიური შეკვეთის მარაგი დაჯავშნილია.
DELETABLE_STATUSES = ("done", "cancelled")


def _valid_phone(phone: str | None) -> bool:
    """მხოლოდ ციფრები, space, +, -, (, ) და 9–15 ციფრი."""
    p = (phone or "").strip()
    if not p or not _PHONE_CHARS.fullmatch(p):
        return False
    return 9 <= sum(c.isdigit() for c in p) <= 15


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

    ⚠️ რევიუ P1-5: ჯერ ატომურ RPC-ს ვცდით (migration 0013). თუ ის ჯერ არ გაშვებულა,
    ძველ „წაიკითხე → ჩაწერე" გზაზე ვბრუნდებით — ე.ი. deploy მიგრაციამდეც უსაფრთხოა
    (იგივე შაბლონი, რაც `_decrement_stock_atomic`-ს აქვს 0009-ისთვის).
    """
    agg: dict[str, int] = {}
    for it in items:
        pid = it.get("product_id")
        if pid:
            agg[pid] = agg.get(pid, 0) + int(it.get("quantity", 0))
    if not agg:
        return

    # --- ატომური გზა (სასურველი) ---
    try:
        sc.rpc(
            "apply_stock_delta",
            {
                "p_shop_id": str(shop_id),
                "p_items": [{"product_id": k, "quantity": v} for k, v in agg.items()],
                "p_sign": int(sign),
            },
        ).execute()
        return
    except APIError as e:
        msg = getattr(e, "message", None) or str(e)
        code = getattr(e, "code", None)
        if not (code in ("42883", "PGRST202") or "does not exist" in msg or "Could not find" in msg):
            logger.warning("apply_stock_delta RPC ჩავარდა (shop=%s): %s", shop_id, msg)
            raise
        # ფუნქცია ჯერ არ არსებობს → legacy გზა ქვემოთ
    except Exception:
        logger.warning("apply_stock_delta RPC მიუწვდომელია (shop=%s)", shop_id, exc_info=True)
        raise

    # --- legacy გზა (არა-ატომური; მხოლოდ 0013-ის გაშვებამდე) ---
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


def _take_stock_for_reopen(sc, shop_id: str, items: list) -> list:
    """გაუქმებულის ხელახლა გახსნა (F-06): მარაგის ატომური აღება decrement_stock-ით
    (ყველაფერი ან არაფერი) — apply_stock_delta(-1)-ის greatest(0, …) აღარ მალავს დეფიციტს.

    წაშლილ პროდუქტს ვტოვებთ (როგორც ძველ გზაზე). აბრუნებს რეალურად დაკლებულ
    ჩანაწერებს — კომპენსაციისთვის. არასაკმარის მარაგზე → 409, მარაგი უცვლელი.
    """
    agg: dict[str, int] = {}
    for it in items:
        pid = it.get("product_id")
        qty = int(it.get("quantity", 0))
        if pid and qty > 0:
            agg[pid] = agg.get(pid, 0) + qty
    if not agg:
        return []
    existing = {
        r["id"]
        for r in sc.table("products")
        .select("id")
        .eq("shop_id", str(shop_id))
        .in_("id", list(agg.keys()))
        .execute()
        .data
    }
    req_items = [{"product_id": k, "quantity": v} for k, v in agg.items() if k in existing]
    if not req_items:
        return []
    try:
        sc.rpc("decrement_stock", {"p_shop_id": str(shop_id), "p_items": req_items}).execute()
    except APIError as e:
        msg = getattr(e, "message", None) or str(e)
        m = re.search(r"INSUFFICIENT_STOCK\|(.*?)\|(\d+)", msg)
        if m:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"შეკვეთის აღდგენა შეუძლებელია — მარაგი არასაკმარისია: {m.group(1)}",
            )
        if "PRODUCT_NOT_FOUND" in msg:
            # პროდუქტი წაიშალა შემოწმებასა და დაკლებას შორის
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "შეკვეთის პროდუქტები ამასობაში შეიცვალა — განაახლე გვერდი და სცადე ხელახლა.",
            )
        logger.warning("decrement_stock (reopen) ჩავარდა (shop=%s): %s", shop_id, msg)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "მარაგის განახლება ვერ მოხერხდა")
    return req_items


def _return_reopen_stock(shop_id: str, taken: list) -> None:
    """ხელახლა გახსნისთვის აღებული მარაგის დაბრუნება, თუ სტატუსი ვერ განახლდა."""
    try:
        _apply_stock_delta(get_service_client(), shop_id, taken, +1)
    except Exception:
        logger.exception(
            "მარაგის კომპენსაცია ჩავარდა შეკვეთის აღდგენის ჩავარდნის შემდეგ "
            "(shop=%s) — მარაგი ხელით უნდა გასწორდეს: %s",
            shop_id, taken,
        )


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

    # ბოტების ფილტრი (FA-04) — ნებისმიერ ჩაწერამდე.
    if (payload.website or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "შეკვეთის შექმნა ვერ მოხერხდა")
    if payload.form_ms < MIN_FORM_MS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "გთხოვთ, შეავსეთ ფორმა და სცადეთ თავიდან."
        )

    if not _valid_phone(payload.customer_phone):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "მიუთითეთ სწორი ტელეფონის ნომერი")

    # ერთი ნომრიდან დაუდასტურებელი შეკვეთების ლიმიტი (ციფრებით შედარება —
    # „+995 555 12-34-56“ == „995555123456“).
    phone_digits = _NON_DIGITS.sub("", payload.customer_phone)
    since_day = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    open_orders = (
        sc.table("orders")
        .select("customer_phone")
        .eq("shop_id", str(payload.shop_id))
        .eq("status", "new")
        .gte("created_at", since_day)
        .execute()
        .data
    )
    same_phone = sum(
        1
        for o in open_orders or []
        if _NON_DIGITS.sub("", o.get("customer_phone") or "") == phone_digits
    )
    if same_phone >= OPEN_ORDERS_PER_PHONE:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "ამ ნომრიდან უკვე გაქვთ 3 დაუდასტურებელი შეკვეთა. "
            "დაელოდეთ მაღაზიის პასუხს ან მიწერეთ Messenger-ში.",
        )

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

    # ერთი პროდუქტის ჯამური რაოდენობა (დუბლირებული ხაზებიც, მაგ. 6+6).
    # უცნობ პროდუქტს ქვემოთ არსებული „ვერ მოიძებნა" გზა იჭერს.
    qty_by_product: dict[str, int] = {}
    for i in payload.items:
        if i.product_id:
            pid = str(i.product_id)
            qty_by_product[pid] = qty_by_product.get(pid, 0) + i.quantity
    for pid, qty in qty_by_product.items():
        prod = price_map.get(pid)
        if prod and qty > MAX_ITEM_QTY:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"„{prod['name']}“ — ერთ შეკვეთაში მაქსიმუმ {MAX_ITEM_QTY} ცალი. "
                "მეტი რაოდენობისთვის მიწერეთ მაღაზიას Messenger-ში.",
            )

    # მაღაზიის საათობრივი ლიმიტი ბაზიდან (გადატვირთვას უძლებს; კონკურენტულად
    # მცირე გადაჭარბება მისაღებია).
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    recent = (
        sc.table("orders")
        .select("id", count="exact")
        .eq("shop_id", str(payload.shop_id))
        .gte("created_at", since)
        .limit(1)
        .execute()
    )
    if (recent.count or 0) >= SHOP_ORDERS_PER_HOUR:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "მაღაზიამ ამ საათში ძალიან ბევრი შეკვეთა მიიღო. "
            "სცადეთ მოგვიანებით ან მიწერეთ მაღაზიას Messenger-ში.",
        )

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
    order_id = None
    try:
        res = sc.table("orders").insert(row).execute()
        if res.data:
            order_id = res.data[0]["id"]
    except Exception:
        logger.exception("order insert failed (shop=%s)", payload.shop_id)
        order_id = None
    if order_id is None:
        # შეკვეთა ვერ ჩაიწერა — დაკლებული მარაგი უკან დავაბრუნოთ.
        # ორივე გზაზე (atomic RPC ან legacy) მარაგი უკვე დაკლებულია აქ მოსვლისას,
        # ამიტომ კომპენსაცია ყოველთვის ხდება (თორემ legacy-ზე მარაგი დაიკარგებოდა).
        try:
            _apply_stock_delta(sc, str(payload.shop_id), items, +1)
        except Exception:
            # კომპენსაციაც ჩავარდა → მარაგი დაკლებული დარჩა. კლიენტს გასაგები
            # შეცდომა უნდა დაუბრუნდეს (და არა 500), მაღაზიას კი ლოგში ვნიშნავთ.
            logger.exception(
                "მარაგის კომპენსაცია ჩავარდა შეკვეთის ჩავარდნის შემდეგ "
                "(shop=%s) — მარაგი ხელით უნდა გასწორდეს: %s",
                payload.shop_id, items,
            )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "შეკვეთის შექმნა ვერ მოხერხდა")

    return {"ok": True, "order_id": order_id, "total": total}


# ---------- გამყიდველი (ავტორიზებული) ----------
@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    auth: CurrentAuth = Depends(get_current_auth),
    status_filter: str | None = Query(default=None, alias="status"),
    shop_id: uuid.UUID | None = Query(default=None, description="ფილტრი კონკრეტული მაღაზიით"),
):
    """მიმდინარე გამყიდველის შეკვეთები (RLS-ით მხოლოდ მისი მაღაზიების).

    ⚠️ რევიუ P2-14: `shop_id` დაემატა. მის გარეშე მრავალ-მაღაზიიანი გამყიდველი
    ყველა მაღაზიის შეკვეთას ერთად ხედავდა, თუმცა პანელში ერთი მაღაზია იყო
    შერჩეული. პარამეტრი **არასავალდებულოა** — გამოტოვებისას ძველი ქცევა რჩება
    (უკან თავსებადი).
    """
    query = auth.client.table("orders").select("*").order("created_at", desc=True)
    if shop_id is not None:
        query = query.eq("shop_id", str(shop_id))
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
    გაუქმებაზე მარაგი უკან ბრუნდება; გაუქმებულის ხელახლა გახსნაზე — ისევ აკლდება
    (ატომურად; არასაკმარის მარაგზე 409)."""
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

    # გაუქმებულის ხელახლა გახსნა (F-06): მარაგი ჯერ ატომურად ავიღოთ — თუ არ
    # ჰყოფნის, 409 და სტატუსი „cancelled" რჩება.
    taken: list = []
    if old_status == "cancelled" and new_status != "cancelled":
        taken = _take_stock_for_reopen(get_service_client(), shop_id, items)

    # ⚠️ ოპტიმისტური ჩაკეტვა (რევიუ P1-4): განახლება მხოლოდ მაშინ გაივლის, თუ
    # სტატუსი ისევ ის არის, რაც ზემოთ წავიკითხეთ. ამის გარეშე ორი ერთდროული
    # მოთხოვნა (ორი ტაბი/მოწყობილობა) ორივე გაივლიდა და მარაგი ორჯერ დაბრუნდებოდა.
    try:
        res = run(
            auth.client.table("orders")
            .update({"status": new_status})
            .eq("id", str(order_id))
            .eq("status", old_status)
        )
    except Exception:
        if taken:
            _return_reopen_stock(shop_id, taken)
        raise
    if not res.data:
        if taken:
            _return_reopen_stock(shop_id, taken)
        # ჩანაწერი არსებობს (ზემოთ წავიკითხეთ), ე.ი. სტატუსი სხვამ შეცვალა.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "შეკვეთის სტატუსი ამასობაში შეიცვალა — განაახლე გვერდი და სცადე ხელახლა.",
        )

    # გაუქმებაზე მარაგის დაბრუნება (ხელახლა გახსნისას მარაგი უკვე ზემოთ აიღო)
    if new_status == "cancelled" and old_status != "cancelled":
        _apply_stock_delta(get_service_client(), shop_id, items, +1)

    return res.data[0]


@router.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(
    order_id: uuid.UUID,
    auth: CurrentAuth = Depends(get_current_auth),
):
    """შეკვეთის წაშლა სიიდან (RLS-ით მხოლოდ საკუთარი).
    მარაგს არ ცვლის — მიწოდებული ნივთი გაყიდულია. მარაგის დასაბრუნებლად
    გამოიყენე „გაუქმებული“ სტატ უსი.
    აქტიური (new/processing) შეკვეთის წაშლა იკრძალება (F-07) — სტატუსის ფილტრი
    თავად DELETE-შია, ამიტომ ერთდროულ სტატუსის ცვლილებასთან ატომურია."""
    res = run(
        auth.client.table("orders")
        .delete()
        .eq("id", str(order_id))
        .in_("status", list(DELETABLE_STATUSES))
    )
    if not res.data:
        cur = run(
            auth.client.table("orders").select("id").eq("id", str(order_id)).limit(1)
        )
        if not cur.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "შეკვეთა ვერ მოიძებნა ან არ არის თქვენი")
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "აქტიური შეკვეთის წაშლა შეუძლებელია — ჯერ გააუქმეთ შეკვეთა (მარაგი დაბრუნდება).",
        )
    return None
