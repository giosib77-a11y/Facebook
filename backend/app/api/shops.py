"""Shops endpoints — გამყიდველის მაღაზიები."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.config import get_settings
from app.core.db import run
from app.core.security import CurrentAuth, get_current_auth
from app.core.tiers import TIER_LABELS, TIER_PRICES, limits_for, normalize_tier
from app.models.shop import ShopCreate, ShopOut
from app.services.pdf_extract import extract_pdf_text

router = APIRouter(prefix="/shops", tags=["shops"])

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10MB


class UpgradeRequestIn(BaseModel):
    tier: str


@router.post("", response_model=ShopOut, status_code=status.HTTP_201_CREATED)
def create_shop(payload: ShopCreate, auth: CurrentAuth = Depends(get_current_auth)):
    """ქმნის მაღაზიას მიმდინარე მომხმარებლის სახელზე.

    owner_id ავტომატურად ისმება auth.uid()-ით; RLS insert პოლისი ამოწმებს, რომ
    owner_id == ავტორიზებული მომხმარებელი.
    """
    data = payload.model_dump(mode="json")
    data["owner_id"] = auth.user_id
    res = run(auth.client.table("shops").insert(data))
    if not res.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "მაღაზიის შექმნა ვერ მოხერხდა")
    return res.data[0]


@router.get("/me", response_model=list[ShopOut])
def my_shops(auth: CurrentAuth = Depends(get_current_auth)):
    """აბრუნებს მიმდინარე მომხმარებლის მაღაზიებს (RLS ისედაც მხოლოდ მათ აჩვენებს)."""
    res = run(
        auth.client.table("shops")
        .select("*")
        .eq("owner_id", auth.user_id)
        .order("created_at")
    )
    return res.data


@router.get("/{shop_id}/usage")
def shop_usage(shop_id: uuid.UUID, auth: CurrentAuth = Depends(get_current_auth)):
    """მაღაზიის პაკეტი + მიმდინარე თვის გამოყენება (usage bar-ისთვის)."""
    shop = run(
        auth.client.table("shops").select("subscription_tier").eq("id", str(shop_id)).limit(1)
    )
    if not shop.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    tier = normalize_tier(shop.data[0].get("subscription_tier"))
    limits = limits_for(tier)
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    cust = run(
        auth.client.table("bot_customers").select("psid", count="exact")
        .eq("shop_id", str(shop_id)).eq("ym", ym).limit(1)
    )
    prods = run(
        auth.client.table("products").select("id", count="exact")
        .eq("shop_id", str(shop_id)).limit(1)
    )
    # მიმდინარე pending მოთხოვნა (თუ migration 0005 გაშვებულია)
    pending = None
    try:
        pr = (
            auth.client.table("upgrade_requests").select("requested_tier")
            .eq("shop_id", str(shop_id)).eq("status", "pending")
            .order("created_at", desc=True).limit(1).execute()
        )
        if pr.data:
            pending = pr.data[0]["requested_tier"]
    except Exception:
        pass
    settings = get_settings()
    return {
        "tier": tier,
        "tier_label": TIER_LABELS[tier],
        "monthly_customers": cust.count or 0,
        "customer_limit": limits["customers"],
        "products": prods.count or 0,
        "product_limit": limits["products"],
        "pending_request": pending,
        "prices": TIER_PRICES,
        "payment_iban": settings.payment_iban,
        "payment_contact": settings.payment_contact,
    }


@router.post("/{shop_id}/upgrade-request")
def request_upgrade(
    shop_id: uuid.UUID,
    payload: UpgradeRequestIn,
    auth: CurrentAuth = Depends(get_current_auth),
):
    """გამყიდველი ითხოვს პაკეტს — ადმინი ხელით დაადასტურებს (გადახდის შემდეგ)."""
    if payload.tier not in TIER_LABELS or payload.tier == "free":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "არასწორი პაკეტი")
    # ძველი pending მოთხოვნები ამ მაღაზიისთვის — ვხურავთ (მხოლოდ ბოლო რჩება)
    try:
        auth.client.table("upgrade_requests").update({"status": "cancelled"}).eq(
            "shop_id", str(shop_id)
        ).eq("status", "pending").execute()
    except Exception:
        pass
    run(
        auth.client.table("upgrade_requests").insert(
            {"shop_id": str(shop_id), "requested_tier": payload.tier, "status": "pending"}
        )
    )
    return {"ok": True}


@router.post("/{shop_id}/knowledge", response_model=ShopOut)
async def upload_knowledge(
    shop_id: uuid.UUID,
    file: UploadFile = File(...),
    auth: CurrentAuth = Depends(get_current_auth),
):
    """ტვირთავ PDF-ს → ტექსტი ამოდის და ინახება მაღაზიის ცოდნად (ბოტი იყენებს)."""
    name = (file.filename or "").lower()
    if not name.endswith(".pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "მხოლოდ .pdf ფაილია მხარდაჭერილი")
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ფაილი ცარიელია")
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ფაილი ძალიან დიდია (მაქს. 10MB)")

    try:
        text = extract_pdf_text(content)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    res = run(
        auth.client.table("shops")
        .update({"knowledge": text, "knowledge_filename": file.filename})
        .eq("id", str(shop_id))
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    return res.data[0]


@router.delete("/{shop_id}/knowledge", response_model=ShopOut)
def clear_knowledge(shop_id: uuid.UUID, auth: CurrentAuth = Depends(get_current_auth)):
    """შლის მაღაზიის ცოდნას (PDF-ინფოს)."""
    res = run(
        auth.client.table("shops")
        .update({"knowledge": None, "knowledge_filename": None})
        .eq("id", str(shop_id))
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    return res.data[0]
