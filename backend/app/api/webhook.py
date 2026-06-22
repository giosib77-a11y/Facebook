"""Facebook Messenger webhook — ვერიფიკაცია + შემოსული შეტყობინებები."""
import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response, status

from app.config import get_settings
from app.core.crypto import decrypt
from app.core.supabase_client import get_service_client
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

    if data.get("object") != "page":
        return {"status": "ignored"}

    # Facebook ელოდება სწრაფ 200-ს — დამუშავება ფონზე
    background_tasks.add_task(_process_events, data)
    return {"status": "ok"}


def _process_events(data: dict) -> None:
    """თითო შემოსულ ტექსტურ შეტყობინებაზე ბოტის პასუხის გაგზავნა."""
    sc = get_service_client()
    for entry in data.get("entry", []):
        page_id = str(entry.get("id"))
        shop_res = (
            sc.table("shops").select("*").eq("facebook_page_id", page_id).limit(1).execute()
        )
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
            try:
                reply = get_bot_reply(shop, products, text, [])
            except Exception:
                reply = "ბოდიში, ამ წუთას ვერ გიპასუხებთ. სცადეთ ცოტა ხანში."
            try:
                send_text_message(page_token, sender_id, reply)
            except Exception:
                pass  # ლოგირება მოგვიანებით
