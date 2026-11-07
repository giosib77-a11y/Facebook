"""Facebook Messenger webhook — ვერიფიკაცია + შემოსული შეტყობინებები."""
import hmac
import json
import logging
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import anyio
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response, status

from app.config import get_settings
from app.core.crypto import decrypt
from app.core.db import fetch_all
from app.core.supabase_client import get_service_client
from app.core.tiers import daily_cap, limits_for
from app.services.facebook import GraphError, download_image, send_text_message, verify_signature
from app.services import budget, inbox, memory, notify
from app.services.graph import run_turn

router = APIRouter(tags=["messenger webhook"])
logger = logging.getLogger("app")

# Meta იმეორებს მოვლენას, თუ 20 წამში 200 არ მიიღო (რევიუ P1-3). dedup — მხოლოდ
# `webhook_inbox unique (page_id, mid)` (0037); legacy გზაზე (dev / ბერკეტი) მეხსიერების dedup
# აღარ არის — Decision Log 2026-11-06.

# FA-12: ცარიელი პასუხი (LLM-მა უარი თქვა / MAX_TOKENS) კლიენტს ჩუმად არ უნდა დაეკარგოს
EMPTY_REPLY_FALLBACK = "ბოდიში, ახლა ვერ გიპასუხებთ — ოპერატორი მალე დაგიკავშირდებათ."
# ლიმიტის გადაჭარბებისას და გამორთული ბოტის (LLM key არ არის) დროს — კლიენტს ვპასუხობთ
# ამ ტექსტით და საუბარს ოპერატორზე ვაგდებთ (needs_attention)
OPERATOR_SOON_REPLY = "მადლობა შეტყობინებისთვის! 🙏 ჩვენი ოპერატორი მალე დაგიკავშირდებათ."
# პლატფორმის ლიმიტზე (Messenger 2000, Instagram 1000) ცოტა ნაკლები — მარაგით
_REPLY_LIMITS = {"page": 1900, "instagram": 900}
_MAX_REPLY_PARTS = 3


def _split_reply(text: str, limit: int) -> list[str]:
    """გრძელი პასუხის დაჭრა ≤limit ნაწილებად (მაქს 3).

    ვჭრით ბოლო "\\n"-ზე ან ". "-ზე ლიმიტამდე, თუ არ არის — ზუსტად ლიმიტზე.
    3-ზე მეტი ნაწილი რომ დასჭირდეს, მესამე ლიმიტზე იჭრება და "…"-ით მთავრდება.
    """
    parts: list[str] = []
    rest = text
    while len(rest) > limit:
        if len(parts) == _MAX_REPLY_PARTS - 1:
            parts.append(rest[: limit - 1].rstrip() + "…")
            return parts
        window = rest[:limit]
        cut = max(window.rfind("\n"), window.rfind(". ") + 1)  # +1 — წერტილი ნაწილში რჩება
        if cut <= 0:
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        parts.append(rest)
    return parts


# S20-20 (A-035): ჩვენ მიერ გაგზავნილი შეტყობინებების id-ები (Send API `message_id`). ჩვენივე პასუხის echo
# ამ id-ით ცნობადია `app_id`-ის გარეშეც (Instagram-ის echo-ს შეიძლება `app_id` არ ჰქონდეს — წინააღმდეგ
# შემთხვევაში ბოტი საკუთარ პასუხზე თავად დაპაუზდებოდა). მეხსიერებაშია, ერთი instance; echo გაგზავნიდან
# წამებში მოდის, ამიტომ 10 წთ ბევრად საკმარისია.
_OUR_MIDS: "OrderedDict[str, float]" = OrderedDict()
_OUR_LOCK = threading.Lock()
_OUR_TTL = 600       # წამი
_OUR_MAX = 5000      # ჩანაწერების ჭერი


def _remember_our_mids(mids) -> None:
    """გაგზავნილი შეტყობინებების id-ების ჩაწერა. არა-სია / ცარიელი / არა-სტრიქონი id — ჩუმად გამოტოვება."""
    if not isinstance(mids, (list, tuple)):
        return
    valid = [m for m in mids if isinstance(m, str) and m]
    if not valid:
        return
    now = time.monotonic()
    with _OUR_LOCK:
        for m in valid:
            _OUR_MIDS.pop(m, None)
            _OUR_MIDS[m] = now
        while len(_OUR_MIDS) > _OUR_MAX:
            _OUR_MIDS.popitem(last=False)


def _is_our_mid(mid) -> bool:
    """True — mid ბოლო `_OUR_TTL` წამში ჩვენ მიერ გაგზავნილია."""
    if not isinstance(mid, str) or not mid:
        return False
    now = time.monotonic()
    with _OUR_LOCK:
        while _OUR_MIDS:
            k, ts = next(iter(_OUR_MIDS.items()))
            if now - ts > _OUR_TTL:
                _OUR_MIDS.pop(k, None)
            else:
                break
        return mid in _OUR_MIDS


# B-3: წუთობრივი ლიმიტი — ერთმა კლიენტმა/მაღაზიამ საერთო LLM კვოტა და threadpool
# არ უნდა ამოწუროს. ლიმიტს გადაცილებულს ჩუმად ვტოვებთ (პასუხი და LLM-ის გამოძახება არ არის).
# მეხსიერებაშია (ერთი instance-ისთვის); ბლოკირებული შეტყობინება არ ითვლება.
_RATE_WINDOW = 60.0       # წამი
_RATE_PER_PSID = 6        # (shop, psid)-ზე წუთში
_RATE_PER_SHOP = 30       # shop-ზე წუთში
_RATE_SWEEP_EVERY = 60.0  # ამ ინტერვალით ვასუფთავებთ ძველ გასაღებებს
_RATE_HITS: "dict[tuple, deque[float]]" = {}
_RATE_LOCK = threading.Lock()
_rate_last_sweep = 0.0


def _rate_limited(shop_id: str, psid: str) -> bool:
    """True — ამ კლიენტმა/მაღაზიამ წუთობრივი ლიმიტი გადააჭარბა (შეტყობინება გამოსატოვებელია)."""
    global _rate_last_sweep
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW
    keys = ((shop_id, psid), (shop_id,))
    limits = (_RATE_PER_PSID, _RATE_PER_SHOP)
    with _RATE_LOCK:
        if now - _rate_last_sweep > _RATE_SWEEP_EVERY or now < _rate_last_sweep:
            _rate_last_sweep = now
            for k in [k for k, q in _RATE_HITS.items() if not q or q[-1] <= cutoff]:
                del _RATE_HITS[k]
        queues = []
        for key, limit in zip(keys, limits):
            q = _RATE_HITS.setdefault(key, deque())
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= limit:
                return True
            queues.append(q)
        for q in queues:
            q.append(now)
    return False


@dataclass
class Conversation:
    """შენახული საუბარი. summary_supported=False — მეხსიერება გამორთულია (`bot_memory_messages <= 0`):
    summary არ იკითხება და upsert-ში `summary` გასაღები არ იგზავნება."""
    messages: list = field(default_factory=list)
    summary: str | None = None
    summary_supported: bool = True


# A-035: handoff-ის / გამყიდველის პასუხის შემდეგ ბოტი ამდენი საათით ჩუმდება
# (ან სანამ პანელში „მოგვარებულია" არ დაჭერილა — რომელიც უფრო ადრე)
BOT_PAUSE_HOURS = 12
_ECHO_TEXT_MAX = 2000
_ECHO_APP_ID_WARNED = False   # FB_APP_ID-ის არარსებობის WARNING — ერთხელ პროცესზე
_GRAPH_TOKEN_ERROR_CODE = 190  # Graph OAuthException: token ვადაგასულია / გაუქმებულია


def _set_bot_status(sc, shop: dict, status: str) -> None:
    """ბოტის ჯანმრთელობის ჩაწერა `shops.bot_status`-ში (migration 0036). არასდროს აგდებს.

    ჩაწერა მხოლოდ ცვლილებაზეა: "ok" ჯანსაღ გზაზე (სტატუსი null/ok) ბაზას არ ეხება, იგივე სტატუსი
    ხელახლა არ იწერება. ჩაწერის ჩავარდნა — WARNING ყოველ ჯერზე (პასუხს არ აფერხებს; გამორთვა არ არის).
    """
    cur = shop.get("bot_status")
    if cur == status or (status == "ok" and cur is None):
        return
    try:
        (
            sc.table("shops")
            .update({"bot_status": status, "bot_status_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", shop["id"]).execute()
        )
    except Exception as e:
        # exc_info / ტექსტი არა: შეცდომის ტექსტში მონაცემი შეიძლება იყოს
        logger.warning("bot status write failed (shop=%s, %s)", shop.get("id"), type(e).__name__)
        return
    shop["bot_status"] = status


def _paused_until(sc, shop_id: str, psid: str) -> datetime | None:
    """საუბრის პაუზის დასასრული, თუ ის ჯერ მომავალშია; პაუზა არ არის / მნიშვნელობა არ იკითხება → None.
    select-ის შეცდომა ზემოთ ადის (inbox-ის გზაზე worker-ის retry)."""
    r = (
        sc.table("bot_conversations").select("bot_paused_until")
        .eq("shop_id", shop_id).eq("psid", psid).limit(1).execute()
    )
    try:
        raw = (r.data or [{}])[0].get("bot_paused_until")
        if not raw:
            return None
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts if ts > datetime.now(timezone.utc) else None
    except Exception:
        return None


def _append_history(sc, shop_id: str, psid: str, new_messages: list, *, pause: bool) -> bool:
    """ისტორიაში შეტყობინებების დამატება LLM-ის გარეშე (გამყიდველის echo / შეჩერებულ საუბარში კლიენტის ტექსტი).

    pause=True → `bot_paused_until` = now + BOT_PAUSE_HOURS. needs_attention / attention_at არ იცვლება.
    ერთი upsert; ჩავარდნა → WARNING და False. True — ჩაიწერა.
    """
    s = get_settings()
    if s.bot_memory_messages <= 0 and not pause:
        return False
    now = datetime.now(timezone.utc)
    conv = _load_conversation(sc, shop_id, psid)
    row: dict = {"shop_id": shop_id, "psid": psid, "updated_at": now.isoformat()}
    if s.bot_memory_messages > 0:
        row["messages"] = (list(conv.messages) + list(new_messages))[-s.bot_memory_messages:]
    if conv.summary_supported:
        row["summary"] = conv.summary  # None ასუფთავებს (ძველი საუბარი)
    if pause:
        row["bot_paused_until"] = (now + timedelta(hours=BOT_PAUSE_HOURS)).isoformat()
    try:
        sc.table("bot_conversations").upsert(row).execute()
        return True
    except Exception as e:
        logger.warning("საუბრის შენახვა ვერ მოხერხდა (shop=%s, %s)", shop_id, type(e).__name__)
        return False


def _handle_echo(sc, shop: dict, ev: dict, obj: str | None = None) -> None:
    """გამყიდველის ხელით დაწერილი პასუხი (message.is_echo): ტექსტი ისტორიაში + ბოტის პაუზა.

    ჩვენი პასუხების ამოცნობა (S20-20), თანმიმდევრობით:
    1. `mid` ჩვენ მიერ ბოლო 10 წთ-ში გაგზავნილია (`_OUR_MIDS`) — ჩვენია; მუშაობს `FB_APP_ID`-ის გარეშეც;
    2. `app_id == FB_APP_ID` — ჩვენია; `FB_APP_ID` ცარიელია → ერთი WARNING და დანარჩენი echo-ები იგნორდება;
    3. Instagram (`obj == "instagram"`) და `app_id` ცარიელი — იგნორდება (გამყიდველის ხელით პასუხის პაუზა
       IG-ზე გამორთულია, სანამ რეალური payload არ დადასტურდება; Decision Log 2026-11-05);
    4. დანარჩენი — გამყიდველია.
    ლოგში psid / ტექსტი არასდროს; `app_id` PII არ არის.
    """
    global _ECHO_APP_ID_WARNED
    message = ev.get("message") or {}
    echo_app_id = str(message.get("app_id") or "").strip()
    logger.info("echo app_id=%s (shop=%s)", echo_app_id[:32] or "none", shop.get("id"))
    if _is_our_mid(message.get("mid")):
        return  # ჩვენი ბოტის (ან ოპერატორის ავტო-) პასუხი
    settings = get_settings()
    app_id = (settings.fb_app_id or "").strip()
    if not app_id:
        if not _ECHO_APP_ID_WARNED:
            _ECHO_APP_ID_WARNED = True
            logger.warning("FB_APP_ID not set - seller replies cannot be told apart; echo ignored")
        return
    if echo_app_id == app_id:
        return  # ჩვენი ბოტის პასუხი
    if obj == "instagram" and not echo_app_id:
        logger.info("instagram echo without app_id ignored (shop=%s)", shop.get("id"))
        return
    psid = (ev.get("recipient") or {}).get("id")
    if not psid:
        return
    text = message.get("text")
    text = text.strip()[:_ECHO_TEXT_MAX] if isinstance(text, str) else ""
    if _append_history(
        sc, str(shop["id"]), str(psid), [{"role": "operator", "content": text or "[დანართი]"}], pause=True,
    ):
        logger.info("seller reply - bot paused (shop=%s)", shop.get("id"))


def _load_conversation(sc, shop_id: str, psid: str) -> Conversation:
    """კლიენტის ბოლო შეტყობინებები + summary (მეხსიერება). select-ის შეცდომა ზემოთ ადის
    (inbox-ის გზაზე worker-ის retry); მეხსიერება გამორთულია (`bot_memory_messages <= 0`) → ცარიელი."""
    s = get_settings()
    if s.bot_memory_messages <= 0:
        return Conversation(summary_supported=False)

    r = (
        sc.table("bot_conversations").select("messages,updated_at,summary")
        .eq("shop_id", shop_id).eq("psid", psid).limit(1).execute()
    )
    try:
        if not r.data:
            return Conversation()
        row = r.data[0]
        try:
            ts = datetime.fromisoformat(str(row["updated_at"]).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - ts > timedelta(hours=s.bot_memory_hours):
                return Conversation()  # ძველი საუბარი — ახლიდან
        except Exception:
            pass
        msgs = row.get("messages") or []
        summary = row.get("summary")
        return Conversation(
            msgs[-s.bot_memory_messages:],
            summary if isinstance(summary, str) and summary.strip() else None,
        )
    except Exception:
        return Conversation()


def _save_turn(
    sc, shop_id: str, psid: str, history: list, user_text: str, bot_reply: str,
    needs_attention: bool = False, *, conv: Conversation | None = None, compact: bool = False,
) -> None:
    """ახალი წყვილის (კლიენტი+ბოტი) შენახვა, ბოლო N-მდე მოჭრით.

    needs_attention=True → საუბარი ინიშნება „ყურადღება სჭირდება"-დ (handoff).
    ჯერ ყოველთვის შეუკუმშავი წყვილი ინახება (ძველი summary-ით) — LLM-ის გამოძახებას შენახვა არ ელოდება,
    ამიტომ მომდევნო შეტყობინება ამ წყვილს კითხულობს და turn არ იკარგება.
    compact=True (agent turn) + conv → თუ შეტყობინებები > memory.HISTORY_CUT, ძველი ნაწილი summary-ში
    იკეცება (LLM გამოძახება, შენახვის შემდეგ) და შედეგი ინახება **პირობითი** update-ით
    (`updated_at` = ახლახან ჩაწერილი): თუ ამასობაში ახალი turn ჩაიწერა, update არაფერს ცვლის და
    შემდეგი agent turn თავიდან შეკუმშავს. ჩავარდნისას memory.compact იგივე სიას აბრუნებს → update არ ხდება.
    conv=None → `summary` გასაღები payload-ში არ არის; conv (compact=False) → ჩატვირთული summary
    ბრუნდება უკან (ძველი საუბრისას None ასუფთავებს).
    """
    s = get_settings()
    if s.bot_memory_messages <= 0 and not needs_attention:
        return
    now = datetime.now(timezone.utc).isoformat()
    full_history = list(history) + [
        {"role": "user", "content": user_text},
        {"role": "bot", "content": bot_reply},
    ]
    summary = conv.summary if conv is not None else None
    stored = full_history[-s.bot_memory_messages:] if s.bot_memory_messages > 0 else full_history[-2:]
    row = {"shop_id": shop_id, "psid": psid, "messages": stored, "updated_at": now}
    if conv is not None and conv.summary_supported:
        row["summary"] = summary  # None ასუფთავებს (ძველი საუბარი)
    if needs_attention:
        row["needs_attention"] = True
        row["attention_at"] = now
        # A-035: handoff-ის შემდეგ ბოტი BOT_PAUSE_HOURS საათით ჩუმდება
        row["bot_paused_until"] = (datetime.now(timezone.utc) + timedelta(hours=BOT_PAUSE_HOURS)).isoformat()
    # ერთი upsert; შეცდომა ზემოთ ადის (ორივე გამომძახებელი WARNING-ით იჭერს — პასუხი უკვე გაგზავნილია)
    sc.table("bot_conversations").upsert(row).execute()
    if not (compact and conv is not None and conv.summary_supported
            and memory.needs_compaction(full_history)):
        return
    kept, new_summary = memory.compact(shop_id, full_history, summary)  # LLM, შენახვის შემდეგ
    if kept is full_history:
        return  # ჩავარდა / არაფერი შეიცვალა — ჩანაწერი უკვე სრულია
    kept = kept[-s.bot_memory_messages:] if s.bot_memory_messages > 0 else kept[-2:]
    try:
        (
            sc.table("bot_conversations").update({"messages": kept, "summary": new_summary})
            .eq("shop_id", shop_id).eq("psid", psid).eq("updated_at", now).execute()
        )
    except Exception:
        logger.warning("conversation compaction save failed (shop=%s)", shop_id, exc_info=True)


# A-021: მხოლოდ ის სვეტები, რასაც ბოტი იყენებს (prompt / tools / ფოტოს რანჟირება), არა select("*").
_BOT_PRODUCT_COLUMNS = "id,name,price,quantity,sku,description,image_url"


# A-041: ცხადი ჭერი; გადაჭარბება — WARNING (პირველი N პროდუქტი), არა ჩუმი ჭრა. Supabase-ის 1000-მწკრივიანი
# ჭერის გამო `fetch_all` კითხულობს გვერდებად. დიდ კატალოგზე ძებნა Postgres-შია (0040) და ჭერს არ ექვემდებარება.
_BOT_PRODUCTS_MAX = 5000


def _load_bot_products(sc, shop_id: str) -> list:
    """მაღაზიის აქტიური პროდუქტები ბოტისთვის. select-ის შეცდომა ზემოთ ადის (inbox-ის გზაზე worker-ის retry)."""
    return fetch_all(
        lambda: (
            sc.table("products").select(_BOT_PRODUCT_COLUMNS + ",image_description")
            .eq("shop_id", shop_id).eq("is_active", True).order("id")
        ),
        max_rows=_BOT_PRODUCTS_MAX,
        label=f"bot products shop={shop_id}",
    )


def _customer_rank(sc, shop_id: str, psid: str) -> int:
    """ამ კლიენტის რიგითი ნომერი (1-დან) მაღაზიის ამ თვის კლიენტებში — მოსვლის მიხედვით.

    ლიმიტის გადაჭარბებისას ვემსახურებით პირველ N-ს და ვბლოკავთ მხოლოდ ახლებს (FA-11).
    """
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    me = (
        sc.table("bot_customers").select("created_at")
        .eq("shop_id", shop_id).eq("ym", ym).eq("psid", psid).limit(1).execute()
    )
    created_at = me.data[0]["created_at"]
    earlier = (
        sc.table("bot_customers").select("psid", count="exact")
        .eq("shop_id", shop_id).eq("ym", ym).lt("created_at", created_at).limit(1).execute()
    )
    if earlier.count is None:
        raise RuntimeError("bot_customers count unavailable")
    return earlier.count + 1


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

    # Facebook ელოდება სწრაფ 200-ს. inbox ჩართულია → მოვლენა ბაზაში ინახება 200-მდე, დამუშავებას worker
    # აკეთებს (restart-ზეც არ იკარგება); გამორთულია (dev / WEBHOOK_INBOX_ENABLED=false) → ფონური დამუშავება.
    # შენახვა ჩავარდა → 503: Meta ხელახლა გამოგზავნის (in-process fallback არ არის — ის ბაზასაც საჭიროებდა).
    if settings.webhook_inbox_active:
        rows = inbox.rows_from_payload(data)
        if not rows:
            return {"status": "ok"}  # შესანახი მოვლენა არ არის (postback / read / delivery / mid-ის გარეშე)
        try:
            await anyio.to_thread.run_sync(inbox.enqueue, get_service_client(), rows)
        except Exception as exc:
            # ლოგში მხოლოდ exception-ის კლასი (ტექსტში payload / psid შეიძლება იყოს)
            logger.error("webhook_inbox enqueue failed (%s) - 503, Meta will retry", type(exc).__name__)
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook queue unavailable")
        inbox.wake()
        return {"status": "ok"}

    background_tasks.add_task(_process_events_limited, data)
    return {"status": "ok"}


async def _process_events_limited(data: dict) -> None:
    """ფონური (legacy) დამუშავება thread-ში, ბოტის საერთო limiter-ით (BOT_MAX_CONCURRENCY)."""
    await anyio.to_thread.run_sync(_process_events, data, limiter=inbox.bot_limiter())


def process_inbox_row(row: dict) -> None:
    """webhook_inbox-ის ერთი მწკრივის დამუშავება (worker იძახებს thread-ში). dedup — ბაზაში (unique).
    შეცდომა ზემოთ ადის → worker `inbox.fail`-ს იძახებს (retry → `failed`)."""
    event = row.get("event")
    if event is None:
        return
    _process_events({"object": row["object"], "entry": [{"id": row["page_id"], "messaging": [event]}]})


def _process_events(data: dict) -> None:
    """თითო შემოსულ ტექსტურ შეტყობინებაზე ბოტის პასუხის გაგზავნა."""
    sc = get_service_client()
    reply_limit = _REPLY_LIMITS.get(data.get("object"), _REPLY_LIMITS["page"])
    for entry in data.get("entry", []):
        # entry.id შეიძლება იყოს Facebook გვერდის ან Instagram ანგარიშის ID.
        # ID ყოველთვის ციფრულია — ვამოწმებთ, რადგან ქვემოთ PostgREST .or_() ფილტრში
        # f-string-ით ერთვის (არა-ციფრს არ ვუშვებთ: filter-injection-ის დაცვა).
        eid = str(entry.get("id") or "")
        if not eid.isdigit():
            continue
        shop_res = (
            sc.table("shops").select("*")
            .or_(f"facebook_page_id.eq.{eid},instagram_account_id.eq.{eid}")
            .limit(2).execute()
        )
        if not shop_res.data:
            continue
        if len(shop_res.data) > 1:
            # A-5: ერთი ID რამდენიმე მაღაზიაზეა (instagram_account_id unique არ იყო) —
            # არასწორი tenant-ის არჩევა მონაცემის გაჟონვაა; ვტოვებთ და ლოგში ვწერთ.
            logger.error(
                "AMBIGUOUS ROUTE: entry.id=%s ემთხვევა %d მაღაზიას — შეტყობინება გამოტოვებულია",
                eid, len(shop_res.data),
            )
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
            _set_bot_status(sc, shop, "token_error")
            notify.alert_bot_down(shop, "token_error")
            continue

        products = _load_bot_products(sc, shop["id"])

        for ev in entry.get("messaging", []):
            message = ev.get("message", {})
            sender_id = (ev.get("sender") or {}).get("id")
            text = message.get("text") or ""
            # სურათის დანართები (Messenger/Instagram) — LLM multimodal-ისთვის
            image_urls = [
                (a.get("payload") or {}).get("url")
                for a in (message.get("attachments") or [])
                if a.get("type") == "image" and (a.get("payload") or {}).get("url")
            ]
            if message.get("is_echo"):
                # A-035: გამყიდველის ხელით დაწერილი პასუხი — ისტორიაში + ბოტის პაუზა
                try:
                    _handle_echo(sc, shop, ev, data.get("object"))
                except Exception as e:
                    # exc_info არა: traceback-ში psid შეიძლება აღმოჩნდეს
                    logger.warning(
                        "echo-ს დამუშავება ვერ მოხერხდა (shop=%s, %s)", shop.get("id"), type(e).__name__,
                    )
                continue
            if not sender_id or (not text and not image_urls):
                continue
            # B-3: წუთობრივი ლიმიტი — ბაზისა და LLM-ის წინ, რომ spam იაფად მოიჭრას
            if _rate_limited(str(shop["id"]), str(sender_id)):
                logger.warning(
                    "წუთობრივი ლიმიტი გადაჭარბდა — შეტყობინება გამოტოვებულია (shop=%s)", shop.get("id"),
                )
                continue

            # A-035: საუბარი შეჩერებულია (handoff / გამყიდველმა უპასუხა) — შეტყობინებას ისტორიაში ვინახავთ,
            # პასუხი არ იგზავნება (LLM, გაგზავნა, ფოტოს ჩამოტვირთვა, კლიენტის თვლა — არა)
            if _paused_until(sc, str(shop["id"]), str(sender_id)):
                _append_history(
                    sc, str(shop["id"]), str(sender_id),
                    [{"role": "user", "content": text or "[სურათი]"}], pause=False,
                )
                logger.info("bot paused - message stored without reply (shop=%s)", shop.get("id"))
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
                if day_count > daily_cap(shop.get("subscription_tier")):
                    continue  # abuse/loop — ჩუმად ვჩერდებით (free 30 / ფასიანი 100)
                limit = int(limits["customers"])
                if monthly > limit:
                    # ლიმიტი გადაჭარბდა — ვბლოკავთ მხოლოდ მათ, ვინც ლიმიტის შემდეგ მოვიდა
                    try:
                        over_limit = _customer_rank(sc, shop["id"], str(sender_id)) > limit
                    except Exception:
                        logger.warning(
                            "კლიენტის რიგის დადგენა ვერ მოხერხდა (shop=%s) — ძველი წესი (ყველა ლიმიტს ზემოთ)",
                            shop.get("id"), exc_info=True,
                        )
                        over_limit = True
            except Exception:
                # ბოტი განზრახ აგრძელებს (კლიენტს არ ვბლოკავთ), მაგრამ ეს იმას ნიშნავს,
                # რომ ლიმიტები ამ შეტყობინებაზე არ გავრცელდა — ლოგი საჭიროა.
                logger.warning(
                    "კლიენტის თვლა ვერ მოხერხდა (shop=%s) — ლიმიტი ამ შეტყობინებაზე არ შემოწმდა",
                    shop.get("id"), exc_info=True,
                )

            # გამორთული ბოტი: არჩეული provider-ის key არ არის. აპი მუშაობს (პანელი), კლიენტი
            # კი ოპერატორთან გადადის. კლიენტი უკვე დათვლილია (track_bot_customer ზემოთაა).
            settings = get_settings()
            bot_disabled = not settings.llm_ready
            if bot_disabled:
                logger.warning(
                    "bot disabled — %s not set (shop=%s)", settings.llm_key_env_name, shop.get("id"),
                )

            # S20-9: LLM-ის ხარჯის კონტროლი (kill-switch / გლობალური დღიური ჭერი / მფლობელის თვიური ბიუჯეტი);
            # უკვე გადაწყვეტილ შემთხვევაზე (over_limit / bot_disabled) ბიუჯეტის RPC არ იძახება.
            # უცნობი ხარჯი (RPC-ის შეცდომა) → None → ბოტი მუშაობს (fail-open).
            reason = None if (over_limit or bot_disabled) else budget.blocked_reason(sc, shop)
            if reason:
                logger.warning("bot budget: %s - operator reply (shop=%s)", reason, shop.get("id"))
                if reason == "monthly_budget":
                    _set_bot_status(sc, shop, "budget_exhausted")

            if over_limit or bot_disabled or reason:
                auto_reply = OPERATOR_SOON_REPLY
                try:
                    _remember_our_mids(send_text_message(page_token, sender_id, auto_reply))
                except Exception:
                    pass
                # გამყიდველმა უნდა დაინახოს ეს კლიენტი „ყურადღება სჭირდება"-ში
                try:
                    # conv= : ჩატვირთული summary უკან იწერება (ძველ საუბარზე None); LLM არ იძახება
                    old_conv = _load_conversation(sc, shop["id"], str(sender_id))
                    _save_turn(
                        sc, shop["id"], str(sender_id), old_conv.messages,
                        text or ("[სურათი]" if image_urls else ""), auto_reply,
                        needs_attention=True, conv=old_conv, compact=False,
                    )
                except Exception:
                    logger.warning("საუბრის შენახვა ვერ მოხერხდა (shop=%s)", shop.get("id"), exc_info=True)
                notify.notify_handoff(sc, shop)  # email მფლობელს (არასდროს აგდებს; throttled)
                continue

            # შემოსული სურათების ჩამოტვირთვა (მაქს 3) — LLM-ისთვის
            images = []
            for url in image_urls[:3]:
                try:
                    img = download_image(url, timeout=8)
                    if img:
                        images.append(img)
                except Exception:
                    pass  # ერთი სურათი ვერ ჩამოიტვირთა — დანარჩენით/ტექსტით ვაგრძელებთ

            conv = _load_conversation(sc, shop["id"], str(sender_id))
            handoff = False
            compact = False  # summary-ის LLM გამოძახება მხოლოდ agent turn-ზე (შაბლონზე/შეცდომაზე — არა)
            try:
                result = run_turn(shop, products, text, conv.messages, images=images, summary=conv.summary)
                reply, handoff = result.text, result.handoff
                compact = result.route == "agent"
            except Exception:
                logger.exception("ბოტის პასუხი ვერ შეიქმნა (shop=%s)", shop.get("id"))
                reply = "ბოდიში, ამ წუთას ვერ გიპასუხებთ. სცადეთ ცოტა ხანში."
            if not reply.strip():
                # FA-12: ცარიელს არ ვაგზავნით — კლიენტს ვპასუხობთ და გამყიდველს ვუნიშნავთ
                logger.warning("ბოტმა ცარიელი პასუხი დააბრუნა (shop=%s)", shop.get("id"))
                reply = EMPTY_REPLY_FALLBACK
                handoff = True
            # მეხსიერებაში ტექსტი ვინახოთ; უტექსტო ფოტოზე — ნიშანი
            saved_text = text or ("[სურათი]" if images else "")
            try:
                # გრძელ პასუხს ნაწილებად ვგზავნით; ჩავარდნისას დანარჩენს აღარ ვაგზავნით
                for part in _split_reply(reply, reply_limit):
                    _remember_our_mids(send_text_message(page_token, sender_id, part))
            except Exception as e:
                # კლიენტმა პასუხი ვერ მიიღო. ვადაგასული page token ასე გამოიყურება.
                logger.exception(
                    "პასუხის გაგზავნა ჩავარდა (shop=%s) — შესაძლოა page token ვადაგასულია",
                    shop.get("id"),
                )
                kind = (
                    "token_expired"
                    if isinstance(e, GraphError) and e.code == _GRAPH_TOKEN_ERROR_CODE
                    else "send_failed"
                )
                _set_bot_status(sc, shop, kind)
                notify.alert_bot_down(shop, kind)
                continue
            _set_bot_status(sc, shop, "ok")
            try:
                _save_turn(
                    sc, shop["id"], str(sender_id), conv.messages, saved_text, reply, handoff,
                    conv=conv, compact=compact,
                )
            except Exception:
                # პასუხი უკვე გაიგზავნა — მეხსიერების ჩაწერის ჩავარდნა კლიენტს არ ეხება
                logger.warning("საუბრის შენახვა ვერ მოხერხდა (shop=%s)", shop.get("id"), exc_info=True)
            if handoff:
                notify.notify_handoff(sc, shop)  # email მფლობელს (არასდროს აგდებს; throttled)
