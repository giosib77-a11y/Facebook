"""Facebook Messenger webhook — ვერიფიკაცია + შემოსული შეტყობინებები."""
import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response, status

from app.config import get_settings
from app.core.crypto import decrypt
from app.core.supabase_client import get_service_client
from app.core.tiers import DAILY_ABUSE_CAP, limits_for
from app.services.bot import get_bot_reply
from app.services.facebook import send_text_message, verify_signature

router = APIRouter(tags=["messenger webhook"])


@router.get("/webhook")
def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    """Meta-ს ვერიფიკაცია: სწორ verify_token-ზე ვაბრუნებთ challenge-ს."""
    settings = get_settings()
    if hub_mode == "subscribe" and hub_verify_token and hub_verify_token == settings.fb_verify_token:
        return Response(content=hub_challenge or "", media_type="text/plain")
    raise HTTPException(status.HTTP_403_FORBIDDEN, "verification failed")


@router.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """შემოსული events — ვამოწმებთ ხელმოწერას და ფონურად ვამუშავებთ (სწრაფი 200)."""
    raw = await request.body()
    settings = get_settings()
    if not verify_signature(settings.fb_app_secret, raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid signature")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid JSON")

    if data.get("object") not in ("page", "instagram"):
        return {"status": "ignored"}

    # Facebook ელოდება სწრაფ 200-ს — დამუშავება ფონზე
    background_tasks.add_task(_process_events, data)
    return {"status": "ok"}


def _process_events(data: dict) -> None:
    """თითო შემოსულ ტექსტურ შეტყობინებაზე ბოტის პასუხის გაგზავნა."""
    sc = get_service_client()
    for entry in data.get("entry", []):
        # entry.id შეიძლება იყოს Facebook გვერდის ან Instagram ანგარიშის ID
        eid = str(entry.get("id"))
        try:
            shop_res = (
                sc.table("shops").select("*")
                .or_(f"facebook_page_id.eq.{eid},instagram_account_id.eq.{eid}")
                .limit(1).execute()
            )
        except Exception:
            # migration 0006 ჯერ არ გაშვებულა (instagram_account_id არ არსებობს) — fallback
            shop_res = sc.table("shops").select("*").eq("facebook_page_id", eid).limit(1).execute()
        if not shop_res.data:
            continue
        shop = shop_res.data[0]
        if not shop.get("bot_enabled") or not shop.get("facebook_page_token"):
            continue

        try:
            page_token = decrypt(shop["facebook_page_token"])
        except Exception:
            continue

        products = (
            sc.table("products")
            .select("*")
            .eq("shop_id", shop["id"])
            .eq("is_active", True)
            .execute()
            .data
        )

        for ev in entry.get("messaging", []):
            message = ev.get("message", {})
            sender_id = (ev.get("sender") or {}).get("id")
            text = message.get("text")
            if message.get("is_echo") or not sender_id or not text:
                continue

            # --- მონეტიზაცია: კლიენტის თვლა + ლიმიტების შემოწმება ---
            over_limit = False
            try:
                r = sc.rpc(
                    "track_bot_customer", {"p_shop": shop["id"], "p_psid": str(sender_id)}
                ).execute()
                row = (r.data or [{}])[0] if isinstance(r.data, list) else (r.data or {})
                monthly = int(row.get("monthly_unique") or 0)
                day_count = int(row.get("day_count") or 0)
                limits = limits_for(shop.get("subscription_tier"))
                if day_count > DAILY_ABUSE_CAP:
                    continue  # abuse/loop — ჩუმად ვჩერდებით
                if monthly > int(limits["customers"]):
                    over_limit = True
            except Exception:
                pass  # თვლა ვერ მოხერხდა — ბოტი მაინც პასუხობს (არ ვბლოკავთ)

            if over_limit:
                try:
                    send_text_message(
                        page_token, sender_id,
                        "მადლობა შეტყობინებისთვის! 🙏 ჩვენი ოპერატორი მალე დაგიკავშირდებათ.",
                    )
                except Exception:
                    pass
                continue

            try:
                reply = get_bot_reply(shop, products, text, [])
            except Exception:
                reply = "ბოდიში, ამ წუთას ვერ გიპასუხებთ. სცადეთ ცოტა ხანში."
            try:
                send_text_message(page_token, sender_id, reply)
            except Exception:
                pass  # ლოგირება მოგვიანებით
