"""Products endpoints — მაღაზიის მარაგის CRUD."""
import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.core.db import run
from app.core.security import CurrentAuth, get_current_auth
from app.core.tiers import limits_for
from app.models.product import ProductCreate, ProductOut, ProductUpdate
from app.services.import_products import parse_products_file, preview_file

router = APIRouter(prefix="/products", tags=["products"])

MAX_IMPORT_BYTES = 5 * 1024 * 1024  # 5MB


def _product_limit_left(auth, shop_id) -> int | None:
    """დარჩენილი პროდუქტების რაოდენობა პაკეტის მიხედვით. None = ულიმიტო.
    თუ migration ჯერ არ გაშვებულა (subscription_tier არ არსებობს) — None (ლიმიტი გამორთ.)."""
    try:
        shop = auth.client.table("shops").select("subscription_tier").eq("id", str(shop_id)).limit(1).execute()
        if not shop.data:
            return None
        limit = limits_for(shop.data[0].get("subscription_tier"))["products"]
        if limit is None:
            return None
        cnt = auth.client.table("products").select("id", count="exact").eq("shop_id", str(shop_id)).limit(1).execute()
        return max(0, limit - (cnt.count or 0))
    except Exception:
        return None


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, auth: CurrentAuth = Depends(get_current_auth)):
    """ამატებს პროდუქტს. RLS insert პოლისი ამოწმებს, რომ shop_id მომხმარებლის
    მაღაზიას ეკუთვნის — სხვისი მაღაზიისთვის ჩაწერა 403-ით ჩავარდება."""
    left = _product_limit_left(auth, payload.shop_id)
    if left is not None and left <= 0:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "პაკეტის ლიმიტს მიაღწიე — მეტი პროდუქტისთვის განაახლე პაკეტი.",
        )
    res = run(auth.client.table("products").insert(payload.model_dump(mode="json")))
    if not res.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "პროდუქტის შექმნა ვერ მოხერხდა")
    return res.data[0]


@router.post("/import/preview")
async def import_preview(
    shop_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    auth: CurrentAuth = Depends(get_current_auth),
):
    """ფაილის სვეტების ნახვა ჩამატებამდე — „სვეტების მორგების" UI-სთვის.

    აბრუნებს: headers (სვეტების სახელები), detected (ავტო-ამოცნობილი mapping),
    preview (პირველი მწკრივები), total_rows.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ფაილი ცარიელია")
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ფაილი ძალიან დიდია (მაქს. 5MB)")
    owns = run(auth.client.table("shops").select("id").eq("id", str(shop_id)).limit(1))
    if not owns.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    try:
        return preview_file(content, file.filename)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.post("/import")
async def import_products(
    shop_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    mapping: str | None = Form(default=None),
    auth: CurrentAuth = Depends(get_current_auth),
):
    """Excel (.xlsx) ან CSV ფაილიდან პროდუქტების bulk-ად დამატება.

    mapping (არასავალდებულო JSON): {"name": 0, "price": 1, "quantity": 2, ...} —
    გამყიდვლის მიერ არჩეული სვეტები. თუ არ არის, სვეტები ავტომატურად ცნობა.
    „all-or-nothing": თუ ფაილში თუნდაც ერთი შეცდომაა, არცერთი არ ემატება და
    ბრუნდება ყველა შეცდომა მწკრივების ნომრებით.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ფაილი ცარიელია")
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ფაილი ძალიან დიდია (მაქს. 5MB)")

    # მაღაზია მომხმარებლის უნდა იყოს (RLS-იც ამოწმებს, მაგრამ ნათელი შეცდომისთვის)
    owns = run(auth.client.table("shops").select("id").eq("id", str(shop_id)).limit(1))
    if not owns.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")

    override = None
    extra_cols = None
    if mapping:
        try:
            raw = json.loads(mapping)
            extra_raw = raw.pop("extra", None)
            override = {k: int(v) for k, v in raw.items() if v is not None and str(v) != ""}
            if extra_raw:
                extra_cols = [int(x) for x in extra_raw]
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "სვეტების მითითება არასწორია")

    try:
        products, errors = parse_products_file(content, file.filename, override, extra_cols)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": f"ფაილში {len(errors)} შეცდომაა — არცერთი პროდუქტი არ დაემატა. გაასწორე და თავიდან ატვირთე.",
                "errors": errors[:100],
            },
        )
    if not products:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "დასამატებელი პროდუქტი ვერ მოიძებნა")

    left = _product_limit_left(auth, shop_id)
    if left is not None and len(products) > left:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"პაკეტის ლიმიტი: კიდევ მხოლოდ {left} პროდუქტის დამატება შეგიძლია. განაახლე პაკეტი.",
        )

    for p in products:
        p["shop_id"] = str(shop_id)
    res = run(auth.client.table("products").insert(products))
    return {"imported": len(res.data or []), "message": f"დაემატა {len(res.data or [])} პროდუქტი"}


@router.get("", response_model=list[ProductOut])
def list_products(
    auth: CurrentAuth = Depends(get_current_auth),
    shop_id: uuid.UUID | None = Query(default=None, description="ფილტრი კონკრეტული მაღაზიით"),
):
    """აბრუნებს მომხმარებლის ყველა პროდუქტს (RLS ფილტრავს); არასავალდებულო shop_id ფილტრით."""
    query = auth.client.table("products").select("*")
    if shop_id is not None:
        query = query.eq("shop_id", str(shop_id))
    res = run(query.order("created_at"))
    return res.data


@router.put("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    auth: CurrentAuth = Depends(get_current_auth),
):
    """ანახლებს პროდუქტს. RLS-ის გამო მხოლოდ საკუთარი პროდუქტი იცვლება;
    წინააღმდეგ შემთხვევაში 404 (ვერ მოიძებნა / არ არის თქვენი)."""
    data = payload.model_dump(mode="json", exclude_unset=True)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "განსაახლებელი ველი არ მითითებულა")
    res = run(
        auth.client.table("products").update(data).eq("id", str(product_id))
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "პროდუქტი ვერ მოიძებნა ან არ არის თქვენი")
    return res.data[0]


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: uuid.UUID, auth: CurrentAuth = Depends(get_current_auth)):
    """შლის პროდუქტს. RLS-ის გამო მხოლოდ საკუთარს; სხვა შემთხვევაში 404."""
    res = run(auth.client.table("products").delete().eq("id", str(product_id)))
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "პროდუქტი ვერ მოიძებნა ან არ არის თქვენი")
    return None
