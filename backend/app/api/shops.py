"""Shops endpoints — გამყიდველის მაღაზიები."""
import json
import re
import uuid
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel

from app.config import get_settings
from app.core.db import run
from app.core.security import CurrentAuth, get_current_auth
from app.core.supabase_client import get_service_client
from app.core.tiers import TIER_LABELS, TIER_PRICES, limits_for, normalize_tier
from app.models.shop import ShopCreate, ShopOut
from app.services.pdf_extract import extract_pdf_text

router = APIRouter(prefix="/shops", tags=["shops"])

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10MB

# ანალიტიკისთვის — ხშირი სასაუბრო სიტყვები (თემად არ ჩავთვლით)
_ANALYTICS_STOPWORDS = {
    "მინდა", "გინდა", "გაქვთ", "გაქვს", "აქვს", "უნდა", "რამე", "კარგი", "არის",
    "როგორ", "ფასი", "ღირს", "რამდენი", "გამარჯობა", "მოიცა", "რომელი", "ხომ",
    "თუ", "რას", "რაში", "ვის", "ვისთვის", "საჩუქრად", "მაჩვენე", "მიჩვენე",
    "გმადლობთ", "მადლობა", "კიდევ", "ესეც", "სხვა", "სურათი", "დიახ", "არა",
    "the", "and", "for", "you", "have", "this", "that", "with",
}


class UpgradeRequestIn(BaseModel):
    tier: str


class ShopSettingsUpdate(BaseModel):
    bot_language: str


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


@router.patch("/{shop_id}", response_model=ShopOut)
def update_shop_settings(
    shop_id: uuid.UUID,
    payload: ShopSettingsUpdate,
    auth: CurrentAuth = Depends(get_current_auth),
):
    """მაღაზიის პარამეტრები — ბოტის ენა (auto / ka / en)."""
    if payload.bot_language not in ("auto", "ka", "en", "ru"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "არასწორი ენა")
    res = run(
        auth.client.table("shops").update({"bot_language": payload.bot_language}).eq("id", str(shop_id))
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    return res.data[0]


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


@router.get("/{shop_id}/attention")
def list_attention(shop_id: uuid.UUID, auth: CurrentAuth = Depends(get_current_auth)):
    """საუბრები, რომლებსაც ოპერატორი სჭირდება (handoff). RLS მხოლოდ საკუთარ მაღაზიას აჩვენებს."""
    try:
        r = (
            auth.client.table("bot_conversations")
            .select("psid,messages,attention_at,updated_at")
            .eq("shop_id", str(shop_id))
            .eq("needs_attention", True)
            .order("attention_at", desc=True)
            .limit(50)
            .execute()
        )
    except Exception:
        # migration 0010 ჯერ არ გაშვებულა
        return {"items": [], "count": 0}

    items = []
    for row in r.data or []:
        msgs = row.get("messages") or []
        last_user = ""
        for m in reversed(msgs):
            if m.get("role") == "user":
                last_user = (m.get("content") or "").strip()
                break
        items.append(
            {
                "psid": row["psid"],
                "last_message": last_user,
                "at": row.get("attention_at") or row.get("updated_at"),
            }
        )
    return {"items": items, "count": len(items)}


@router.post("/{shop_id}/attention/{psid}/resolve")
def resolve_attention(
    shop_id: uuid.UUID, psid: str, auth: CurrentAuth = Depends(get_current_auth)
):
    """გამყიდველი მონიშნავს, რომ საუბარი მოგვარდა (flag ჩამოიხსნება)."""
    # მფლობელობის შემოწმება RLS-ით
    owns = run(auth.client.table("shops").select("id").eq("id", str(shop_id)).limit(1))
    if not owns.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    # განახლება service_role-ით (bot_conversations-ს owner-update პოლისი არ აქვს)
    try:
        get_service_client().table("bot_conversations").update(
            {"needs_attention": False}
        ).eq("shop_id", str(shop_id)).eq("psid", psid).execute()
    except Exception:
        pass
    return {"ok": True}


@router.get("/{shop_id}/export")
def export_shop_data(shop_id: uuid.UUID, auth: CurrentAuth = Depends(get_current_auth)):
    """მონაცემთა გადატანა (portability) — გამყიდველი ჩამოტვირთავს თავის მაღაზიას,
    პროდუქტებსა და შეკვეთებს ერთ JSON ფაილად. RLS-ით მხოლოდ საკუთარი მაღაზია;
    დაშიფრულ ტოკენს არ ვაბრუნებთ (credential-ია, არა მომხმარებლის მონაცემი)."""
    shop = run(auth.client.table("shops").select("*").eq("id", str(shop_id)).limit(1))
    if not shop.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    shop_row = dict(shop.data[0])
    shop_row.pop("facebook_page_token", None)  # საიდუმლო — არ გადის ექსპორტში

    products = run(
        auth.client.table("products").select("*").eq("shop_id", str(shop_id)).order("name")
    ).data
    orders = run(
        auth.client.table("orders").select("*").eq("shop_id", str(shop_id))
        .order("created_at", desc=True)
    ).data

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "shop": shop_row,
        "products": products,
        "orders": orders,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    fname = f"chatassist-export-{datetime.now(timezone.utc):%Y-%m-%d}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/{shop_id}/analytics")
def shop_analytics(shop_id: uuid.UUID, auth: CurrentAuth = Depends(get_current_auth)):
    """ბოტის ანალიტიკა — რას კითხულობენ კლიენტები + უპასუხო (handoff) საუბრები.

    RLS-ით მხოლოდ საკუთარი მაღაზიის საუბრები. მიგრაცია 0008/0010-მდე — ცარიელი.
    """
    owns = run(auth.client.table("shops").select("id").eq("id", str(shop_id)).limit(1))
    if not owns.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")

    empty = {"total_conversations": 0, "needs_attention": 0, "top_terms": [], "recent_questions": []}
    try:
        rows = (
            auth.client.table("bot_conversations")
            .select("messages,needs_attention,updated_at")
            .eq("shop_id", str(shop_id))
            .order("updated_at", desc=True)
            .limit(500)
            .execute()
            .data
        ) or []
    except Exception:
        return empty  # migration ჯერ არ გაშვებულა

    attention = 0
    questions: list[str] = []
    for r in rows:
        if r.get("needs_attention"):
            attention += 1
        for m in r.get("messages") or []:
            if m.get("role") == "user":
                c = (m.get("content") or "").strip()
                if c and c != "[სურათი]":
                    questions.append(c)

    counter: Counter = Counter()
    for q in questions:
        for t in re.split(r"\W+", q.lower()):
            if len(t) >= 3 and t not in _ANALYTICS_STOPWORDS:
                counter[t] += 1

    return {
        "total_conversations": len(rows),
        "needs_attention": attention,
        "top_terms": [{"term": t, "count": c} for t, c in counter.most_common(12)],
        "recent_questions": questions[:25],
    }


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
