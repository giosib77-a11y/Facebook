"""Shops endpoints — გამყიდველის მაღაზიები."""
import json
import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel

from app.config import get_settings
from app.core.db import run
from app.core.ratelimit import rate_limit
from app.core.security import CurrentAuth, get_current_auth
from app.core.supabase_client import get_service_client
from app.core.tiers import (
    TIER_LABELS,
    TIER_LIMITS,
    TIER_PRICES,
    best_tier,
    bulk_import_allowed,
    limits_for,
    normalize_tier,
    owner_shop_limit,
)
from app.models.shop import ShopCreate, ShopOut
from app.services.bot_limits import enforce_bot_limit
from app.services.knowledge import build_faq
from app.services.pdf_extract import extract_pdf_text

router = APIRouter(prefix="/shops", tags=["shops"])
logger = logging.getLogger("app")

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


def _cancel_pending_requests(shop_ids: list[str]) -> None:
    """ამ მაღაზიების pending upgrade-მოთხოვნების გაუქმება (service_role).

    `upgrade_requests`-ს გამყიდველისთვის UPDATE პოლისი არ აქვს, ამიტომ გაუქმება
    service client-ით ხდება; მფლობელობა გამომძახებელს უკვე RLS-ით აქვს შემოწმებული.
    შეცდომას არ ვყლაპავთ (S12-3): ჩუმი ჩავარდნისას ერთ მფლობელს რამდენიმე pending
    დარჩებოდა და ადმინს ძველი/იაფი მოთხოვნის დადასტურება შეეძლებოდა.
    """
    if not shop_ids:
        return
    (
        get_service_client().table("upgrade_requests")
        .update({"status": "cancelled"})
        .in_("shop_id", [str(i) for i in shop_ids])
        .eq("status", "pending")
        .execute()
    )


_SHOP_LIMIT_TEXT = (
    "პაკეტის ლიმიტი: მეტი მაღაზიის დასამატებლად განაახლე პაკეტი "
    "(სტანდარტი — 2 მაღაზია, ბიზნესი — ულიმიტო)."
)


@router.post("", response_model=ShopOut, status_code=status.HTTP_201_CREATED)
def create_shop(payload: ShopCreate, auth: CurrentAuth = Depends(get_current_auth)):
    """ქმნის მაღაზიას მიმდინარე მომხმარებლის სახელზე.

    owner_id ყოველთვის auth.user_id-ია (payload-იდან არასდროს). INSERT
    გამყიდველს ჩამორთმეული აქვს (0015), ამიტომ ჩაწერა service_role-ით ხდება —
    ლიმიტის შემოწმების შემდეგ.
    """
    # მაღაზიების ჭერი — მფლობელის უმაღლესი პაკეტის მიხედვით (free/basic=1, standard=2, business=∞)
    existing = run(
        auth.client.table("shops").select("subscription_tier").eq("owner_id", auth.user_id)
    )
    owned = existing.data or []
    tiers = [s.get("subscription_tier") for s in owned]
    limit = owner_shop_limit(tiers)
    if limit is not None and len(owned) >= limit:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _SHOP_LIMIT_TEXT)
    data = payload.model_dump(mode="json")
    data["owner_id"] = auth.user_id
    # per-account: ახალი მაღაზია მემკვიდრეობით იღებს მფლობელის მიმდინარე პაკეტს —
    # ერთი გამოწერა ფარავს ყველა მაღაზიას (მაგ. სტანდარტის მე-2 მაღაზია ცალკე გადახდას არ ითხოვს)
    data["subscription_tier"] = best_tier(tiers)
    rows = _insert_shop_atomic(data, limit)
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "მაღაზიის შექმნა ვერ მოხერხდა")
    return rows[0]


# migration 0032 ჯერ არ არის გაშვებული (PGRST202) → ძველი გზა; flag პროცესზე ერთხელ ჩაირთვება
_CREATE_SHOP_RPC_MISSING = False


def _insert_shop_atomic(data: dict, limit: int | None) -> list:
    """ლიმიტის შემოწმება + INSERT ერთ ტრანზაქციაში (RPC `create_shop_limited`, A-029).

    pre-check (`create_shop`-ში) მხოლოდ სწრაფი უარია; პარალელური მოთხოვნების race-ს RPC-ის
    advisory lock ფარავს. `core.db.run` აქ განზრახ არ გამოიყენება — გვჭირდება შეცდომის კოდი/ტექსტი.
    """
    global _CREATE_SHOP_RPC_MISSING
    sc = get_service_client()
    if not _CREATE_SHOP_RPC_MISSING:
        try:
            res = sc.rpc(
                "create_shop_limited",
                {
                    "p_owner": data["owner_id"],
                    "p_name": data["name"],
                    "p_description": data.get("description"),
                    "p_currency": data.get("currency"),
                    "p_tier": data["subscription_tier"],
                    "p_limit": limit,
                },
            ).execute()
            return res.data or []
        except Exception as exc:
            message = getattr(exc, "message", None) or str(exc)
            if "shop_limit_reached" in message or "shop_limit_reached" in str(exc):
                raise HTTPException(status.HTTP_403_FORBIDDEN, _SHOP_LIMIT_TEXT)
            if getattr(exc, "code", None) == "PGRST202":
                _CREATE_SHOP_RPC_MISSING = True
                logger.warning(
                    "create_shop_limited missing (migration 0032 not applied) - "
                    "shop limit check is not atomic"
                )
            else:
                logger.warning("create_shop_limited failed (%s)", type(exc).__name__)
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "მაღაზიის შექმნა ვერ მოხერხდა")
    return run(sc.table("shops").insert(data)).data or []


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
    # მიმდინარე pending მოთხოვნა (თუ migration 0005 გაშვებულია). per-account: RLS (ur_owner_select)
    # მხოლოდ მფლობელის მაღაზიების მოთხოვნებს აჩვენებს, ამიტომ shop_id-ით არ ვფილტრავთ.
    pending = None
    try:
        pr = (
            auth.client.table("upgrade_requests").select("requested_tier")
            .eq("status", "pending")
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
        "bulk_import": bulk_import_allowed(tier),
        "pending_request": pending,
        "prices": TIER_PRICES,
        "payment_iban": settings.payment_iban,
        "payment_contact": settings.payment_contact,
    }


@router.post(
    "/{shop_id}/upgrade-request",
    dependencies=[Depends(rate_limit("upgrade_request", 10, 3600))],
)
def request_upgrade(
    shop_id: uuid.UUID,
    payload: UpgradeRequestIn,
    auth: CurrentAuth = Depends(get_current_auth),
):
    """გამყიდველი ითხოვს პაკეტს — ადმინი ხელით დაადასტურებს (გადახდის შემდეგ).

    გამოწერა per-account-ია, ამიტომ pending მოთხოვნა მფლობელზე ერთია: ახალი მოთხოვნა
    მისი ყველა მაღაზიის ძველ pending-ს აუქმებს. ჩაწერა service client-ით (0024:
    authenticated-ს INSERT აღარ აქვს) მას შემდეგ, რაც მფლობელობა RLS-ით დადასტურდა.
    """
    if payload.tier not in TIER_LABELS or payload.tier == "free":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "არასწორი პაკეტი")
    # RLS: auth.client მხოლოდ მფლობელის საკუთარ მაღაზიებს ხედავს
    owned = run(auth.client.table("shops").select("id"))
    owned_ids = [str(r["id"]) for r in owned.data or []]
    if str(shop_id) not in owned_ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    try:
        _cancel_pending_requests(owned_ids)
        run(
            get_service_client().table("upgrade_requests").insert(
                {"shop_id": str(shop_id), "requested_tier": payload.tier, "status": "pending"}
            )
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("upgrade request ვერ შეინახა (owner=%s)", auth.user_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "მოთხოვნა ვერ შეინახა — სცადე ხელახლა.")
    return {"ok": True}


@router.post("/{shop_id}/downgrade-free")
def downgrade_to_free(shop_id: uuid.UUID, auth: CurrentAuth = Depends(get_current_auth)):
    """გამყიდველი აუქმებს გამოწერას → მთელი ანგარიში (ყველა მისი მაღაზია) უფასოზე ბრუნდება.

    გამოწერა per-account-ია (ერთი გადახდა ფარავს ყველა მაღაზიას), ამიტომ გაუქმებაც
    ყველა მაღაზიას ეხება. subscription_tier / bot_enabled გამყიდველს ჩაწერად
    არ აქვს (0015) → service_role-ით, ყოველთვის `owner_id = auth.user_id` ფილტრით.
    pending upgrade მოთხოვნებიც უქმდება.

    ⚠️ რევიუ P1-6 — ლიმიტების გავრცელება არსებულ მაღაზიებზე:
    ადრე downgrade მხოლოდ ტარიფს ცვლიდა და ხუთივე მაღაზიის ბოტი აგრძელებდა
    მუშაობას — ე.ი. ერთი თვის გადახდით მუდმივი უპირატესობა რჩებოდა.
    ახლა ლიმიტს ზემოთ მყოფ მაღაზიებზე **ბოტი ითიშება**.

    ᲛᲝᲜᲐᲪᲔᲛᲘ ᲐᲠ ᲘᲨᲚᲔᲑᲐ: მაღაზიები, პროდუქტები და შეკვეთები ხელუხლებელი რჩება.
    ითიშება მხოლოდ `bot_enabled` (ერთი დროშა), რომელიც პაკეტის დაბრუნებისას
    ავტომატურად ბრუნდება (იხ. admin.py — approve/tier-ცვლილება).
    ბოტი ყველაზე ძველ მაღაზიებზე რჩება ჩართული (რაც უფრო სავარაუდოა მთავარი).
    """
    res = run(
        get_service_client().table("shops")
        .update({"subscription_tier": "free"})
        .eq("owner_id", auth.user_id)
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")

    shop_ids = [s["id"] for s in res.data]
    try:
        _cancel_pending_requests(shop_ids)
    except Exception:
        logger.exception("downgrade: pending მოთხოვნების გაუქმება ვერ მოხერხდა (owner=%s)", auth.user_id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "პაკეტი შეიცვალა, მაგრამ მოთხოვნების გაუქმება ვერ მოხერხდა — სცადე ხელახლა.",
        )

    # ბოტის ჭერი უფასო პაკეტზე (free → 1): ყველაზე ძველი ჩართული რჩება, დანარჩენი ითიშება.
    # შეცდომას არ ვყლაპავთ: tier უკვე უფასოა, ზედმეტი ბოტი კი მუშაობს → 500, გამეორება იდემპოტენტურია.
    try:
        disabled = [d["name"] or d["id"] for d in enforce_bot_limit(get_service_client(), auth.user_id)]
    except Exception:
        logger.exception("downgrade: ბოტის გათიშვა ვერ მოხერხდა (owner=%s)", auth.user_id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "პაკეტი შეიცვალა, მაგრამ ბოტების გათიშვა ვერ მოხერხდა — სცადე ხელახლა.",
        )
    limit = TIER_LIMITS["free"]["shops"]

    msg = "უფასო პაკეტზე დაბრუნდი."
    if disabled:
        msg += (
            f" უფასო პაკეტი {limit} მაღაზიას მოიცავს, ამიტომ ბოტი გაითიშა: "
            + ", ".join(disabled)
            + ". მონაცემები დარჩა — პაკეტის დაბრუნებისას ბოტიც ავტომატურად ჩაირთვება."
        )
    return {"ok": True, "tier": "free", "bot_disabled": disabled, "message": msg}


_PAUSE_COLUMN_WARNED = False  # bot_paused_until-ის არარსებობის WARNING — ერთხელ პროცესზე


def _warn_pause_missing() -> None:
    """migration 0033-ის გარეშე პანელის პაუზის ფუნქციები გამორთულია — WARNING ერთხელ პროცესზე."""
    global _PAUSE_COLUMN_WARNED
    if _PAUSE_COLUMN_WARNED:
        return
    _PAUSE_COLUMN_WARNED = True
    logger.warning(
        "bot_conversations.bot_paused_until missing (migration 0033 not applied) - panel pause list disabled"
    )


def _future_iso(raw) -> str | None:
    """`bot_paused_until` → ISO (UTC), თუ ის მომავალშია; სხვა შემთხვევაში (ან ცუდი მნიშვნელობა) None."""
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts = ts.astimezone(timezone.utc)
    except ValueError:
        return None
    return ts.isoformat() if ts > datetime.now(timezone.utc) else None


@router.get("/{shop_id}/attention")
def list_attention(shop_id: uuid.UUID, auth: CurrentAuth = Depends(get_current_auth)):
    """საუბრები, რომლებსაც ოპერატორი სჭირდება (handoff) ან ბოტი შეჩერებულია (A-035).
    RLS მხოლოდ საკუთარ მაღაზიას აჩვენებს."""
    # `+` URL-ში არ უნდა მოხვდეს (PostgREST-ში space-ად იკითხება) — ამიტომ Z ფორმატი
    now_z = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pause_supported = True
    try:
        r = (
            auth.client.table("bot_conversations")
            .select("psid,messages,attention_at,updated_at,needs_attention,bot_paused_until")
            .eq("shop_id", str(shop_id))
            .or_(f"needs_attention.eq.true,bot_paused_until.gte.{now_z}")
            .order("updated_at", desc=True)
            .limit(50)
            .execute()
        )
    except Exception:
        # migration 0033 ჯერ არ გაშვებულა → ძველი query (მხოლოდ needs_attention)
        _warn_pause_missing()
        pause_supported = False
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
            return {"items": [], "count": 0, "attention_count": 0}

    items = []
    for row in r.data or []:
        msgs = row.get("messages") or []
        last_user = ""
        for m in reversed(msgs):
            if m.get("role") == "user":
                last_user = (m.get("content") or "").strip()
                break
        needs = True if not pause_supported else bool(row.get("needs_attention"))
        items.append(
            {
                "psid": row["psid"],
                "last_message": last_user,
                # მხოლოდ შეჩერებულ საუბარს attention_at ძველი handoff-იდან შეიძლება დარჩენოდა
                "at": (row.get("attention_at") or row.get("updated_at")) if needs else row.get("updated_at"),
                "needs_attention": needs,
                "paused_until": _future_iso(row.get("bot_paused_until")) if pause_supported else None,
            }
        )
    attention_count = sum(1 for i in items if i["needs_attention"])
    return {"items": items, "count": len(items), "attention_count": attention_count}


@router.post("/{shop_id}/attention/{psid}/resolve")
def resolve_attention(
    shop_id: uuid.UUID, psid: str, auth: CurrentAuth = Depends(get_current_auth)
):
    """გამყიდველი მონიშნავს, რომ საუბარი მოგვარდა (flag ჩამოიხსნება)."""
    # მფლობელობის შემოწმება RLS-ით
    owns = run(auth.client.table("shops").select("id").eq("id", str(shop_id)).limit(1))
    if not owns.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    # განახლება service_role-ით (bot_conversations-ს owner-update პოლისი არ აქვს);
    # „მოგვარებულია" პაუზასაც ხსნის (A-035)
    sc = get_service_client()
    try:
        sc.table("bot_conversations").update(
            {"needs_attention": False, "bot_paused_until": None}
        ).eq("shop_id", str(shop_id)).eq("psid", psid).execute()
    except Exception:
        # migration 0033 ჯერ არ გაშვებულა → მხოლოდ flag
        _warn_pause_missing()
        try:
            sc.table("bot_conversations").update(
                {"needs_attention": False}
            ).eq("shop_id", str(shop_id)).eq("psid", psid).execute()
        except Exception:
            pass
    return {"ok": True}


@router.post("/{shop_id}/attention/{psid}/resume")
def resume_bot(shop_id: uuid.UUID, psid: str, auth: CurrentAuth = Depends(get_current_auth)):
    """„ბოტის ჩართვა": საუბრის პაუზა მოიხსნება (needs_attention უცვლელია). A-035."""
    owns = run(auth.client.table("shops").select("id").eq("id", str(shop_id)).limit(1))
    if not owns.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    try:
        get_service_client().table("bot_conversations").update(
            {"bot_paused_until": None}
        ).eq("shop_id", str(shop_id)).eq("psid", psid).execute()
    except Exception as e:
        # psid ლოგში არ იწერება
        logger.warning("ბოტის ჩართვა ვერ მოხერხდა (shop=%s, %s)", shop_id, type(e).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ბოტის ჩართვა ახლა ვერ მოხერხდა — სცადეთ მოგვიანებით.",
        )
    return {"ok": True, "paused_until": None}


@router.delete("/{shop_id}/customers/{psid}")
def delete_customer_data(shop_id: uuid.UUID, psid: str, auth: CurrentAuth = Depends(get_current_auth)):
    """კლიენტის მონაცემების წაშლა (A-039): გამყიდველი შლის ამ მაღაზიაში კლიენტის (PSID)
    საუბარს და თვიურ მრიცხველს. Meta-ს Data Deletion callback კლიენტებს არ ეხება (ASID ≠ PSID)."""
    if not re.fullmatch(r"[0-9]{1,32}", psid):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "არასწორი კლიენტის იდენტიფიკატორი")
    owns = run(auth.client.table("shops").select("id").eq("id", str(shop_id)).limit(1))
    if not owns.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    sc = get_service_client()
    try:
        sc.table("bot_conversations").delete().eq("shop_id", str(shop_id)).eq("psid", psid).execute()
        sc.table("bot_customers").delete().eq("shop_id", str(shop_id)).eq("psid", psid).execute()
    except Exception as e:
        # psid ლოგში არ იწერება
        logger.warning("customer data deletion failed (shop=%s, %s)", shop_id, type(e).__name__)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "კლიენტის მონაცემების წაშლა ვერ მოხერხდა — სცადეთ ხელახლა.",
        )
    logger.info("customer data deleted (shop=%s)", shop_id)
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


# Stage 17: "shops.knowledge_faq missing" გაფრთხილება — პროცესზე მაქსიმუმ ერთხელ
_faq_column_warned = [False]


def _write_knowledge(shop_id: uuid.UUID, payload: dict):
    """ცოდნის ჩაწერა service client-ით (ერთი update, ფილტრი `id` კოდში). თუ migration 0027 ჯერ არ არის
    გაშვებული (შეცდომა `knowledge_faq` სვეტზე), იგივე update ამ გასაღების გარეშე — ატვირთვა მაინც ინახება.
    სხვა შეცდომა ვრცელდება როგორც ადრე (APIError → HTTP, `run`-ით). `run` production-ში ბაზის ტექსტს
    ფარავს, ამიტომ სვეტის შეცდომას execute-ზე ვცნობთ, `run`-მდე.
    აბრუნებს `(res, faq_column_ok)`; `False` = სვეტი არ არის და ეს ჩაწერა მის გარეშე მოხდა."""
    missing: list[bool] = []

    def attempt(data: dict):
        query = get_service_client().table("shops").update(data).eq("id", str(shop_id))

        def execute():
            try:
                return query.execute()
            except Exception as exc:
                if "knowledge_faq" in str(exc):
                    missing.append(True)
                raise

        return run(SimpleNamespace(execute=execute))

    try:
        return attempt(payload), True
    except Exception:
        if not missing:
            raise
    if not _faq_column_warned[0]:
        _faq_column_warned[0] = True
        logger.warning("shops.knowledge_faq missing (migration 0027 not applied) - knowledge FAQ disabled")
    return attempt({k: v for k, v in payload.items() if k != "knowledge_faq"}), False


def _build_and_save_faq(shop_id: uuid.UUID, text: str) -> None:
    """Background (upload-ის response-ის შემდეგ): FAQ → `knowledge_faq`. **არასდროს აგდებს**; ლოგში მხოლოდ
    shop id და exception-ის კლასი. FAQ ინახება მხოლოდ თუ მაღაზიის ცოდნა ჯერ ისევ **იგივე ტექსტია**:
    შუალედში ხელახალი ატვირთვა (სხვა ტექსტი) ან წაშლა (`knowledge = null`) ძველ FAQ-ს არ მიიღებს.
    დარდება ტექსტის პირდაპირი შედარებით (წაკითხვა → შედარება → ჩაწერა), არა `updated_at`-ით: `shops`-ის
    trigger (0001) ყოველ update-ზე, მათ შორის სახელის/აღწერის ცვლილებაზე, მას ცვლის და FAQ-ს უსაფუძვლოდ
    დაბლოკავდა; 50K სიმბოლოიანი `knowledge` კი URL-ის ფილტრში არ ეტევა. შედარებიდან ჩაწერამდე რჩება
    მილიწამების ფანჯარა; მასში ხელახლა ატვირთულ ტექსტს თავისი FAQ მაინც გადააწერს."""
    try:
        faq = build_faq(str(shop_id), text)  # არასდროს აგდებს; None → ჩაწერა არ სჭირდება (null უკვე ჩაწერილია)
        if faq is None:
            return
        sc = get_service_client()
        cur = sc.table("shops").select("knowledge").eq("id", str(shop_id)).limit(1).execute()
        if not cur.data or cur.data[0].get("knowledge") != text:
            return  # შუალედში სხვა ტექსტი ატვირთეს ან ცოდნა წაშალეს — ეს FAQ მოძველებულია
        sc.table("shops").update({"knowledge_faq": faq}).eq("id", str(shop_id)).execute()
    except Exception as exc:
        logger.warning("knowledge FAQ save failed (shop=%s, %s)", shop_id, type(exc).__name__)


@router.post(
    "/{shop_id}/knowledge",
    response_model=ShopOut,
    dependencies=[Depends(rate_limit("knowledge_upload", 10, 3600))],
)
def upload_knowledge(
    shop_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    auth: CurrentAuth = Depends(get_current_auth),
):
    """ტვირთავ PDF-ს → ტექსტი ამოდის და ინახება მაღაზიის ცოდნად (ბოტი იყენებს) ერთი ჩაწერით
    (`knowledge_faq = null`) და response მაშინვე ბრუნდება. Stage 17: ტექსტიდან მოკლე FAQ (`knowledge_faq`)
    ერთი LLM გამოძახებით background-ში იქმნება და ინახება, თუ ცოდნა ჯერ ისევ იგივეა; მანამდე (ან
    ჩავარდნაზე) ბოტი ძველებურად მუშაობს — ცოდნის პირველი 20 000 სიმბოლო. ლიმიტი 10/საათში (IP-ზე),
    რადგან ატვირთვა LLM-ს ხარჯავს."""
    # PDF ცოდნა — მხოლოდ ფასიან პაკეტზე (ტიპის შემოწმება + მფლობელობა RLS-ით)
    shop = run(
        auth.client.table("shops").select("subscription_tier").eq("id", str(shop_id)).limit(1)
    )
    if not shop.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    if not bulk_import_allowed(shop.data[0].get("subscription_tier")):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "PDF ცოდნის ატვირთვა ფასიან პაკეტშია ხელმისაწვდომი — განაახლე პაკეტი.",
        )
    name = (file.filename or "").lower()
    if not name.endswith(".pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "მხოლოდ .pdf ფაილია მხარდაჭერილი")
    content = file.file.read(MAX_PDF_BYTES + 1)
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ფაილი ცარიელია")
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ფაილი ძალიან დიდია (მაქს. 10MB)")

    try:
        text = extract_pdf_text(content)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    # ჩაწერა service client-ით (0022: authenticated-ს knowledge* სვეტებზე UPDATE აღარ აქვს);
    # მფლობელობა ზემოთ auth.client-ის RLS select-ით უკვე დადასტურდა.
    # knowledge_faq: None — ძველი დოკუმენტის FAQ ახალ ტექსტს არ რჩება
    res, faq_column_ok = _write_knowledge(
        shop_id,
        {"knowledge": text, "knowledge_filename": (file.filename or "")[:255], "knowledge_faq": None},
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    if faq_column_ok:  # 0027 არ არის გაშვებული → FAQ-ის LLM გამოძახება აზრს მოკლებულია
        background_tasks.add_task(_build_and_save_faq, shop_id, text)
    return res.data[0]


@router.delete("/{shop_id}/knowledge", response_model=ShopOut)
def clear_knowledge(shop_id: uuid.UUID, auth: CurrentAuth = Depends(get_current_auth)):
    """შლის მაღაზიის ცოდნას (PDF-ინფოს) და მისგან შექმნილ FAQ-ს (LLM-ის გარეშე)."""
    # მფლობელობა RLS-ით (auth.client); ჩაწერა service client-ით (0022: authenticated-ს
    # knowledge* სვეტებზე UPDATE აღარ აქვს), ამიტომ ფილტრი `id` კოდში ცხადია.
    owned = run(auth.client.table("shops").select("id").eq("id", str(shop_id)).limit(1))
    if not owned.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    res, _ = _write_knowledge(
        shop_id, {"knowledge": None, "knowledge_filename": None, "knowledge_faq": None}
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    return res.data[0]
