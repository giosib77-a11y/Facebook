"""გამყიდველის Facebook გვერდის დაკავშირების flow (OAuth)."""
import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from fastapi.responses import HTMLResponse

from app.config import get_settings
from app.core.crypto import encrypt
from app.core.db import run
from app.core.security import CurrentAuth, get_current_auth
from app.core.supabase_client import get_service_client
from app.services import facebook as fb

router = APIRouter(prefix="/facebook", tags=["facebook connect"])
logger = logging.getLogger("app")


def _public_base() -> str:
    """საჯარო base URL — public_base_url, თუ არა → fb_redirect_uri-ის დომენი, თუ არა → frontend_url."""
    s = get_settings()
    if s.public_base_url:
        return s.public_base_url.rstrip("/")
    if s.fb_redirect_uri:
        return s.fb_redirect_uri.split("/facebook/")[0].rstrip("/")
    return s.frontend_url.rstrip("/")


def _finish(result: str, **params) -> HTMLResponse:
    """ამთავრებს OAuth-ს: თუ popup-ია, შეტყობინებას უგზავნის მთავარ ფანჯარას დაიხურება;
    თუ არა (popup დაბლოკილი), მთავარ პანელზე გადაამისამართებს (fallback)."""
    s = get_settings()
    data = {"fb": result, **params}
    fallback = f"{s.frontend_url.rstrip('/')}/?{urlencode(data)}"
    # postMessage-ს კონკრეტულ origin-ებზე ვგზავნით (არა '*'), რომ შედეგი უცხო
    # გვერდმა ვერ წაიკითხოს. პანელი ორ ადგილას შეიძლება იხსნებოდეს (frontend_url ან
    # backend /panel), ამიტომ ორივე ცნობილ origin-ზე ვცდით — არასწორ origin-ზე
    # postMessage ჩუმად იგნორდება, ამიტომ არაფერი „ჟონავს" და flow-ც არ იტეხება.
    allowed: list[str] = []
    for u in (s.frontend_url, _public_base()):
        o = (u or "").rstrip("/")
        if o and o not in allowed:
            allowed.append(o)
    html = (
        "<!doctype html><html><head><meta charset='utf-8'></head>"
        "<body style='font-family:sans-serif;text-align:center;padding:40px'>"
        "<p>მუშავდება, დაიცადეთ...</p><script>(function(){var msg=" + json.dumps(data) + ";"
        "var origins=" + json.dumps(allowed) + ";"
        "try{if(window.opener&&!window.opener.closed){"
        "for(var i=0;i<origins.length;i++){try{window.opener.postMessage(msg,origins[i]);}catch(e){}}"
        "window.close();return;}}catch(e){}"
        "window.location.replace(" + json.dumps(fallback) + ");})();</script></body></html>"
    )
    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# Data Deletion — დადასტურების კოდი (რევიუ P2-16)
#
# ადრე კოდი `uuid4()`-ით იქმნებოდა და არსად ინახებოდა, ე.ი. status-გვერდი
# ნებისმიერ ტექსტს „დადასტურებულად" აჩვენებდა. Meta-ს განმხილველი სწორედ ამ
# ნაკადს ამოწმებს.
#
# გამოსავალი — ხელმოწერილი (stateless) კოდი: ცხრილი არ გვჭირდება, ბაზა არ
# იზრდება, გასუფთავება არ სჭირდება, და კოდი მაინც შემოწმებადია.
# ფორმატი: <base64url(uid_hash:ts)>.<hmac16>
# ---------------------------------------------------------------------------
_DELETION_CODE_TTL = 400 * 24 * 3600  # ~13 თვე — Meta-ს შემოწმებას დროის მარაგი ჰქონდეს


def _deletion_secret() -> bytes:
    return (get_settings().fb_app_secret or "chatassist").encode()


def make_deletion_code(user_id: str) -> str:
    """ხელმოწერილი, შემოწმებადი დადასტურების კოდი. user_id ღიად არ გადის (hash-დება)."""
    uid_hash = hashlib.sha256(str(user_id).encode() + _deletion_secret()).hexdigest()[:12]
    raw = base64.urlsafe_b64encode(f"{uid_hash}:{int(time.time())}".encode()).decode().rstrip("=")
    sig = hmac.new(_deletion_secret(), raw.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{raw}.{sig}"


def verify_deletion_code(code: str) -> dict | None:
    """აბრუნებს {"requested_at": ISO} თუ კოდი ნამდვილია, სხვა შემთხვევაში None."""
    try:
        raw, sig = (code or "").rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(_deletion_secret(), raw.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        padded = raw + "=" * (-len(raw) % 4)
        _uid_hash, ts = base64.urlsafe_b64decode(padded.encode()).decode().split(":")
        ts = int(ts)
    except Exception:
        return None
    if time.time() - ts > _DELETION_CODE_TTL:
        return None
    return {"requested_at": datetime.fromtimestamp(ts, timezone.utc).isoformat()}


@router.get("/connect/start")
def connect_start(shop_id: uuid.UUID, auth: CurrentAuth = Depends(get_current_auth)):
    """ამოწმებს რომ მაღაზია მომხმარებლისაა და აბრუნებს Facebook login URL-ს."""
    res = run(auth.client.table("shops").select("id").eq("id", str(shop_id)).limit(1))
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა")
    state = fb.sign_state({"shop_id": str(shop_id), "user_id": auth.user_id, "ts": time.time()})
    return {"login_url": fb.build_login_url(state)}


@router.get("/connect/callback")
def connect_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """Facebook-ის redirect: code -> page token -> შენახვა shop-ში + webhook subscribe."""
    if error or not code or not state:
        return _finish("error", reason=error or "missing_code")

    data = fb.verify_state(state)
    if not data:
        return _finish("error", reason="invalid_state")

    try:
        user_token = fb.exchange_code_for_token(code)
        user_token = fb.exchange_for_long_lived(user_token)
        pages = fb.get_user_pages(user_token)
    except Exception as e:
        return _finish("error", reason=f"graph:{e}")

    if not pages:
        return _finish("no_pages")

    page = pages[0]  # პირველი გვერდი (მომავალში — არჩევანი)
    page_id, page_token, page_name = page["id"], page["access_token"], page.get("name", "")

    try:
        fb.subscribe_page(page_id, page_token)
    except Exception as e:
        return _finish("error", reason=f"subscribe:{e}")

    # გვერდზე მიბმული Instagram Business ანგარიში (თუ არსებობს) — IG-ბოტისთვის
    ig_account_id = None
    try:
        ig_account_id = fb.get_page_instagram_account(page_id, page_token)
    except Exception:
        pass  # IG არასავალდებულოა — გვერდი მაინც დაუკავშირდება

    # დამაკავშირებელი FB user-id — Data Deletion callback-ისთვის (არასავალდებულო)
    fb_user_id = None
    try:
        fb_user_id = fb.get_user_id(user_token)
    except Exception:
        pass

    sc = get_service_client()
    upd = {
        "facebook_page_id": page_id,
        "facebook_page_token": encrypt(page_token),
        "instagram_account_id": ig_account_id,
        "facebook_user_id": fb_user_id,
        "bot_enabled": True,
    }

    def _save(payload: dict):
        return (
            sc.table("shops").update(payload)
            .eq("id", data["shop_id"]).eq("owner_id", data["user_id"]).execute()
        )

    try:
        res = _save(upd)
    except Exception as e:
        msg = str(e)
        # ⚠️ რევიუ P2-13: facebook_page_id გლობალურად unique-ია. თუ ეს გვერდი უკვე
        # სხვა მაღაზიაზეა მიბმული, აქ unique-violation მოდის — ადრე ეს fallback-ს
        # გადაეცემოდა, იქაც ვარდებოდა და მომხმარებელი popup-ში 500-ს ხედავდა.
        if "duplicate key" in msg or "23505" in msg or "already exists" in msg:
            logger.warning("გვერდი %s უკვე დაკავშირებულია სხვა მაღაზიაზე", page_id)
            return _finish("error", reason="page_taken")
        # migration 0006/0011 ჯერ არ გაშვებულა — ამ ველების გარეშე მაინც ვცდით
        upd.pop("instagram_account_id", None)
        upd.pop("facebook_user_id", None)
        try:
            res = _save(upd)
        except Exception:
            logger.exception("გვერდის შენახვა ჩავარდა (shop=%s)", data.get("shop_id"))
            return _finish("error", reason="save_failed")

    # ⚠️ რევიუ P2-13: შედეგი უნდა შემოწმდეს. 0 მწკრივი ნიშნავს, რომ მაღაზია
    # აღარ არსებობს ან სხვას ეკუთვნის — ადრე ასეთ დროსაც „connected" ბრუნდებოდა.
    if not (res.data or []):
        logger.warning(
            "გვერდის შენახვამ 0 მწკრივი შეცვალა (shop=%s, user=%s)",
            data.get("shop_id"), data.get("user_id"),
        )
        return _finish("error", reason="shop_not_found")

    return _finish("connected", page=page_name)


@router.post("/data-deletion")
def data_deletion_callback(signed_request: str = Form(...)):
    """Meta Data Deletion Callback — როცა მომხმარებელი აპს წაშლის, Facebook აქ POST-ავს.

    ვამოწმებთ signed_request-ს app_secret-ით, ვშლით ამ მომხმარებლის (PSID) საუბრებს
    და ვაბრუნებთ Meta-ს მოთხოვნილ JSON-ს: {url, confirmation_code}.
    """
    s = get_settings()
    data = fb.parse_signed_request(signed_request, s.fb_app_secret)
    if not data or not data.get("user_id"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid signed_request")

    user_id = str(data["user_id"])
    sc = get_service_client()

    # 1. გამყიდველი ამ Facebook user-id-ით — გავთიშოთ გვერდი + წავშალოთ მისი საუბრები.
    #    (facebook_user_id ინახება connect-ზე; migration 0011-მდე ეს ბლოკი ჩუმად გამოტოვდება.)
    try:
        shops = (
            sc.table("shops").select("id").eq("facebook_user_id", user_id).execute().data or []
        )
        for s in shops:
            try:
                sc.table("bot_conversations").delete().eq("shop_id", s["id"]).execute()
            except Exception:
                pass
            sc.table("shops").update(
                {
                    "facebook_page_id": None,
                    "facebook_page_token": None,
                    "instagram_account_id": None,
                    "bot_enabled": False,
                }
            ).eq("id", s["id"]).execute()
    except Exception:
        pass  # facebook_user_id სვეტი შეიძლება არ არსებობდეს — fallback ქვემოთ

    # 2. fallback: თუ user_id კლიენტის psid-ია — ვშლით მის საუბრებს
    try:
        sc.table("bot_conversations").delete().eq("psid", user_id).execute()
    except Exception:
        pass  # Meta-ს მაინც ვპასუხობთ წარმატებით

    # ხელმოწერილი კოდი — status-გვერდს შეუძლია მისი ნამდვილობის შემოწმება (P2-16)
    code = make_deletion_code(user_id)
    return {
        "url": f"{_public_base()}/panel/delete-data.html?code={code}",
        "confirmation_code": code,
    }


@router.get("/data-deletion/status")
def data_deletion_status(code: str):
    """დადასტურების კოდის შემოწმება — delete-data.html ამას იძახებს.

    Meta-ს მოთხოვნაა, რომ status-URL-მა წაშლის მდგომარეობა აჩვენოს. ხელმოწერის
    გარეშე გვერდი ნებისმიერ ტექსტს „დადასტურებულად" აჩვენებდა.
    """
    info = verify_deletion_code(code)
    if not info:
        return {"valid": False, "status": "unknown"}
    return {"valid": True, "status": "completed", "requested_at": info["requested_at"]}


@router.post("/disconnect")
def disconnect(shop_id: uuid.UUID, auth: CurrentAuth = Depends(get_current_auth)):
    """გვერდის გათიშვა — ასუფთავებს page მონაცემებს და თიშავს ბოტს."""
    res = run(
        auth.client.table("shops")
        .update({"facebook_page_id": None, "facebook_page_token": None, "instagram_account_id": None, "bot_enabled": False})
        .eq("id", str(shop_id))
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    return {"status": "disconnected"}
