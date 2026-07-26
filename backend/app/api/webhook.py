"""Facebook Messenger webhook — ვერიფიკაცია + შემოსული შეტყობინებები."""
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response, status

from app.config import get_settings
from app.core.crypto import decrypt
from app.core.supabase_client import get_service_client
from app.core.tiers import DAILY_ABUSE_CAP, limits_for
from app.services.bot import get_bot_reply, parse_reply
from app.services.facebook import send_text_message, verify_signature

router = APIRouter(tags=["messenger webhook"])


def _load_history(sc, shop_id: str, psid: str) -> list:
    """კლიენტის ბოლო შეტყობინებები (მეხსიერება). migration 0008-ის გარეშე — [] (უმეხსიერებოდ)."""
    s = get_settings()
    if s.bot_memory_messages <= 0:
        return []
    try:
        r = (
            sc.table("bot_conversations").select("messages,updated_at")
            .eq("shop_id", shop_id).eq("psid", psid).limit(1).execute()
        )
        if not r.data:
            return []
        row = r.data[0]
        try:
            ts = datetime.fromisoformat(str(row["updated_at"]).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - ts > timedelta(hours=s.bot_memory_hours):
                return []  # ძველი საუბარი — ახლიდან
        except Exception:
            pass
        msgs = row.get("messages") or []
        return msgs[-s.bot_memory_messages:]
    except Exception:
        return []


def _save_turn(
    sc, shop_id: str, psid: str, history: list, user_text: str, bot_reply: str,
    needs_attention: bool = False,
) -> None:
    """ახალი წყვილის (კლიენტი+ბოტი) შენახვა, ბოლო N-მდე მოჭრით.

    needs_attention=True → საუბარი ინიშნება „ყურადღება სჭირდება"-დ (handoff).
    """
    s = get_settings()
    if s.bot_memory_messages <= 0 and not needs_attention:
        return
    now = datetime.now(timezone.utc).isoformat()
    new = list(history) + [
        {"role": "user", "content": user_text},
        {"role": "bot", "content": bot_reply},
    ]
    new = new[-s.bot_memory_messages:] if s.bot_memory_messages > 0 else new[-2:]
    base = {"shop_id": shop_id, "psid": psid, "messages": new, "updated_at": now}
    full = dict(base)
    if needs_attention:
        full["needs_attention"] = True
        full["attention_at"] = now
    try:
        sc.table("bot_conversations").upsert(full).execute()
    except Exception:
        # migration 0010 ჯერ არ გაშვებულა (needs_attention არ არსებობს) — მეხსიერება მაინც შევინახოთ
        if needs_attention:
            try:
                sc.table("bot_conversations").upsert(base).execute()
            except Exception:
                pass


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

            history = _load_history(sc, shop["id"], str(sender_id))
            handoff = False
            try:
                reply, handoff = parse_reply(get_bot_reply(shop, products, text, history))
            except Exception:
                reply = "ბოდიში, ამ წუთას ვერ გიპასუხებთ. სცადეთ ცოტა ხანში."
            try:
                send_text_message(page_token, sender_id, reply)
                _save_turn(sc, shop["id"], str(sender_id), history, text, reply, handoff)
            except Exception:
                pass  # ლოგირება მოგვიანებით
