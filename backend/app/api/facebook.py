"""გამყიდველის Facebook გვერდის დაკავშირების flow (OAuth)."""
import json
import time
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse

from app.config import get_settings
from app.core.crypto import encrypt
from app.core.db import run
from app.core.security import CurrentAuth, get_current_auth
from app.core.supabase_client import get_service_client
from app.services import facebook as fb

router = APIRouter(prefix="/facebook", tags=["facebook connect"])


def _finish(result: str, **params) -> HTMLResponse:
    """ამთავრებს OAuth-ს: თუ popup-ია, შეტყობინებას უგზავნის მთავარ ფანჯ არ ას და იხ ურება;
    თუ არა (popup დაბლოკილი), მთავარ პანელზე გადაამისამართებს (fallback)."""
    data = {"fb": result, **params}
    fallback = f"{get_settings().frontend_url.rstrip('/')}/?{urlencode(data)}"
    html = (
        "<!doctype html><html><head><meta charset='utf-8'></head>"
        "<body style='font-family:sans-serif;text-align:center;padding:40px'>"
        "<p>მუშავდება, დაიცადეთ...</p><script>(function(){var msg=" + json.dumps(data) + ";"
        "try{if(window.opener&&!window.opener.closed){window.opener.postMessage(msg,'*');window.close();return;}}catch(e){}"
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

    sc = get_service_client()
    sc.table("shops").update(
        {
            "facebook_page_id": page_id,
            "facebook_page_token": encrypt(page_token),
            "bot_enabled": True,
        }
    ).eq("id", data["shop_id"]).eq("owner_id", data["user_id"]).execute()

    return _finish("connected", page=page_name)


@router.post("/disconnect")
def disconnect(shop_id: uuid.UUID, auth: CurrentAuth = Depends(get_current_auth)):
    """გვერდის გათიშვა — ასუფთავებს page მონაცემებს და თიშავს ბოტს."""
    res = run(
        auth.client.table("shops")
        .update({"facebook_page_id": None, "facebook_page_token": None, "bot_enabled": False})
        .eq("id", str(shop_id))
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "მაღაზია ვერ მოიძებნა ან არ არის თქვენი")
    return {"status": "disconnected"}
