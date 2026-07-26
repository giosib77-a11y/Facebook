"""ბოტის ტესტ-endpoint — Messenger-ის გარეშე გასატესტად.

⚠️ დროებითი / DEV: ეს endpoint ავთენტიფიკაციას არ მოითხოვს და მაღაზიის მარაგს
service_role-ით კითხულობს (როგორც რეალური ბოტი წაიკითხავს Messenger-იდან).
Facebook-ის ინტეგრაცია მოვა მომდევნო ნაბიჯზე; production-ში ეს endpoint მოიხსნება
ან დაიცვება.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.core.ratelimit import rate_limit
from app.core.supabase_client import get_service_client
from app.models.chat import TestChatRequest, TestChatResponse
from app.services.bot import get_bot_reply, parse_reply

router = APIRouter(tags=["bot (dev)"])


@router.post(
    "/test-chat",
    response_model=TestChatResponse,
    dependencies=[Depends(rate_limit("test_chat", limit=15, window=60))],
)
def test_chat(payload: TestChatRequest):
    settings = get_settings()
    # DEV-only endpoint — production-ში დახურულია (დაუცველად Gemini-ს იძახებს).
    if settings.is_production:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY არ არის კონფიგურირებული .env-ში",
        )

    sc = get_service_client()
    shop_res = (
        sc.table("shops").select("*").eq("id", str(payload.shop_id)).limit(1).execute()
    )
    if not shop_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა")
    shop = shop_res.data[0]

    # ბოტს მხოლოდ აქტიური პროდუქტები აინტერესებს
    products = (
        sc.table("products")
        .select("*")
        .eq("shop_id", str(payload.shop_id))
        .eq("is_active", True)
        .order("created_at")
        .execute()
        .data
    )

    try:
        reply, _ = parse_reply(
            get_bot_reply(
                shop, products, payload.message, [t.model_dump() for t in payload.history]
            )
        )
    except RuntimeError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    except Exception as e:  # Gemini-ის ან ქსელის შეცდომა
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ბოტის შეცდომა: {e}")

    return TestChatResponse(
        reply=reply, products_in_context=len(products), model=settings.gemini_model
    )
