"""გამყიდველის Facebook გვერდის დაკავშირების flow (OAuth)."""
import json
import time
import uuid
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
    try:
        sc.table("shops").update(upd).eq("id", data["shop_id"]).eq("owner_id", data["user_id"]).execute()
    except Exception:
        # migration 0006/0011 ჯერ არ გაშვებულა — ამ ველების გარეშე მაინც დავაკავშიროთ
        upd.pop("instagram_account_id", None)
        upd.pop("facebook_user_id", None)
        sc.table("shops").update(upd).eq("id", data["shop_id"]).eq("owner_id", data["user_id"]).execute()

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

    code = uuid.uuid4().hex[:16]
    return {
        "url": f"{_public_base()}/panel/delete-data.html?code={code}",
        "confirmation_code": code,
    }


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
