"""Facebook Messenger webhook — ვერიფიკაცია + შემოსული შეტყობინებები."""
import hmac
import json
import logging
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response, status

from app.config import get_settings
from app.core.crypto import decrypt
from app.core.supabase_client import get_service_client
from app.core.tiers import DAILY_ABUSE_CAP, limits_for
from app.services.bot import get_bot_reply, parse_reply
from app.services.facebook import download_image, send_text_message, verify_signature

router = APIRouter(tags=["messenger webhook"])
logger = logging.getLogger("app")

# ⚠️ რევიუ P1-3: Meta იმეორებს მოვლენას, თუ 20 წამში 200 არ მიიღო. გამეორება
# ორმაგ პასუხს და ორმაგად დათვლილ შეტყობინებას იწვევდა. აქ ბოლო message id-ებს
# ვიმახსოვრებთ და გამეორებულს ვტოვებთ.
# შეზღუდვა: მეხსიერებაშია, ე.ი. ერთი instance-ის ფარგლებში მუშაობს. Render-ზე
# ერთი instance გვაქვს, ამიტომ პრაქტიკულ შემთხვევებს ფარავს. მრავალ-instance-ზე
# გადასვლისას → Redis ან ბაზის ცხრილი.
_SEEN_MIDS: "OrderedDict[str, float]" = OrderedDict()
_SEEN_TTL = 600      # წამი — ამაზე ძველს ვივიწყებთ
_SEEN_MAX = 5000     # ჩანაწერების ჭერი (მეხსიერება არ გაიბეროს)


def _already_handled(mid: str | None) -> bool:
    """True — თუ ეს შეტყობინება უკვე დამუშავდა (Meta-ს გამეორება)."""
    if not mid:
        return False  # id-ის გარეშე ვერ გავარჩევთ — ვამუშავებთ
    now = time.time()
    while _SEEN_MIDS:
        k, ts = next(iter(_SEEN_MIDS.items()))
        if now - ts > _SEEN_TTL:
            _SEEN_MIDS.pop(k, None)
        else:
            break
    if mid in _SEEN_MIDS:
        return True
    _SEEN_MIDS[mid] = now
    while len(_SEEN_MIDS) > _SEEN_MAX:
        _SEEN_MIDS.popitem(last=False)
    return False


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
    if (
        hub_mode == "subscribe"
        and hub_verify_token
        and settings.fb_verify_token
        and hmac.compare_digest(hub_verify_token, settings.fb_verify_token)
    ):
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
        # entry.id შეიძლება იყოს Facebook გვერდის ან Instagram ანგარიშის ID.
        # ID ყოველთვის ციფრულია — ვამოწმებთ, რადგან ქვემოთ PostgREST .or_() ფილტრში
        # f-string-ით ერთვის (არა-ციფრს არ ვუშვებთ: filter-injection-ის დაცვა).
        eid = str(entry.get("id") or "")
        if not eid.isdigit():
            continue
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
            # ⚠️ ბოტი ამ მაღაზიაზე მკვდარია. ყველაზე ხშირი მიზეზი —
            # FB_TOKEN_ENCRYPTION_KEY შეიცვალა და ძველი ჩანაწერი აღარ იშიფრება.
            # ადრე ეს ჩუმად ხდებოდა და ხუთივე მაღაზია გაითიშა შეუმჩნევლად.
            logger.error(
                "BOT DOWN: page token-ის გაშიფვრა ვერ მოხერხდა (shop=%s, page=%s) — "
                "შეამოწმე FB_TOKEN_ENCRYPTION_KEY ან ხელახლა დააკავშირე გვერდი",
                shop.get("id"), eid,
            )
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
            text = message.get("text") or ""
            # სურათის დანართები (Messenger/Instagram) — Gemini multimodal-ისთვის
            image_urls = [
                (a.get("payload") or {}).get("url")
                for a in (message.get("attachments") or [])
                if a.get("type") == "image" and (a.get("payload") or {}).get("url")
            ]
            if message.get("is_echo") or not sender_id or (not text and not image_urls):
                continue
            # Meta-ს გამეორებული მოვლენა — ერთხელ უკვე ვუპასუხეთ (P1-3)
            if _already_handled(message.get("mid")):
                logger.info("გამეორებული შეტყობინება იგნორდა (mid=%s)", message.get("mid"))
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
                # ბოტი განზრახ აგრძელებს (კლიენტს არ ვბლოკავთ), მაგრამ ეს იმას ნიშნავს,
                # რომ ლიმიტები ამ შეტყობინებაზე არ გავრცელდა — ლოგი საჭიროა.
                logger.warning(
                    "კლიენტის თვლა ვერ მოხერხდა (shop=%s) — ლიმიტი ამ შეტყობინებაზე არ შემოწმდა",
                    shop.get("id"), exc_info=True,
                )

            if over_limit:
                try:
                    send_text_message(
                        page_token, sender_id,
                        "მადლობა შეტყობინებისთვის! 🙏 ჩვენი ოპერატორი მალე დაგიკავშირდებათ.",
                    )
                except Exception:
                    pass
                continue

            # შემოსული სურათების ჩამოტვირთვა (მაქს 3) — Gemini-სთვის
            images = []
            for url in image_urls[:3]:
                try:
                    img = download_image(url, timeout=8)
                    if img:
                        images.append(img)
                except Exception:
                    pass  # ერთი სურათი ვერ ჩამოიტვირთა — დანარჩენით/ტექსტით ვაგრძელებთ

            history = _load_history(sc, shop["id"], str(sender_id))
            handoff = False
            try:
                reply, handoff = parse_reply(
                    get_bot_reply(shop, products, text, history, images=images)
                )
            except Exception:
                logger.exception("ბოტის პასუხი ვერ შეიქმნა (shop=%s)", shop.get("id"))
                reply = "ბოდიში, ამ წუთას ვერ გიპასუხებთ. სცადეთ ცოტა ხანში."
            # მეხსიერებაში ტექსტი ვინახოთ; უტექსტო ფოტოზე — ნიშანი
            saved_text = text or ("[სურათი]" if images else "")
            try:
                send_text_message(page_token, sender_id, reply)
            except Exception:
                # კლიენტმა პასუხი ვერ მიიღო. ვადაგასული page token ასე გამოიყურება.
                logger.exception(
                    "პასუხის გაგზავნა ჩავარდა (shop=%s, psid=%s) — შესაძლოა page token ვადაგასულია",
                    shop.get("id"), sender_id,
                )
                continue
            try:
                _save_turn(sc, shop["id"], str(sender_id), history, saved_text, reply, handoff)
            except Exception:
                # პასუხი უკვე გაიგზავნა — მეხსიერების ჩაწერის ჩავარდნა კლიენტს არ ეხება
                logger.warning("საუბრის შენახვა ვერ მოხერხდა (shop=%s)", shop.get("id"), exc_info=True)
