"""Facebook Graph API ჰელპერები — ხელმოწერა, OAuth, Send API, state.

Send API + OAuth ცოცხალ Meta App-ს მოითხოვს; ხელმოწერისა და state-ის ლოგიკა
offline-ად ტესტირებადია.
"""
import base64
import hashlib
import hmac
import json
import time

import httpx

from app.config import get_settings

# ---- OAuth scope: Messenger + Instagram-ისთვის საჭირო ნებართვები ----
OAUTH_SCOPES = (
    "pages_show_list,pages_messaging,pages_manage_metadata,"
    "instagram_basic,instagram_manage_messages"
)


def _graph_base() -> str:
    return f"https://graph.facebook.com/{get_settings().fb_graph_version}"


# ---------------------------------------------------------------------------
# X-Hub-Signature-256 ვერიფიკაცია
# ---------------------------------------------------------------------------
def verify_signature(app_secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    """ამოწმებს, რომ მოთხოვნა მართლა Facebook-იდან მოვიდა (app secret-ით)."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    sent = signature_header.split("=", 1)[1]
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sent)


# ---------------------------------------------------------------------------
# OAuth state — ხელმოწერილი (CSRF + shop/user-ის გადატანა)
# ---------------------------------------------------------------------------
def sign_state(data: dict) -> str:
    secret = get_settings().fb_app_secret.encode()
    raw = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    sig = hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_state(state: str, max_age_seconds: int = 600) -> dict | None:
    try:
        raw, sig = state.rsplit(".", 1)
    except ValueError:
        return None
    secret = get_settings().fb_app_secret.encode()
    expected = hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except Exception:
        return None
    if time.time() - data.get("ts", 0) > max_age_seconds:
        return None
    return data


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------
def build_login_url(state: str) -> str:
    s = get_settings()
    from urllib.parse import urlencode

    params = {
        "client_id": s.fb_app_id,
        "redirect_uri": s.fb_redirect_uri,
        "scope": OAUTH_SCOPES,
        "response_type": "code",
        "state": state,
    }
    return f"https://www.facebook.com/{s.fb_graph_version}/dialog/oauth?{urlencode(params)}"


def exchange_code_for_token(code: str) -> str:
    """authorization code -> short-lived user access token."""
    s = get_settings()
    r = httpx.get(
        f"{_graph_base()}/oauth/access_token",
        params={
            "client_id": s.fb_app_id,
            "client_secret": s.fb_app_secret,
            "redirect_uri": s.fb_redirect_uri,
            "code": code,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def exchange_for_long_lived(user_token: str) -> str:
    """short-lived -> long-lived user token (page token-ებიც გრძელვადიანი ხდება)."""
    s = get_settings()
    r = httpx.get(
        f"{_graph_base()}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": s.fb_app_id,
            "client_secret": s.fb_app_secret,
            "fb_exchange_token": user_token,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def get_user_pages(user_token: str) -> list[dict]:
    """მომხმარებლის გვერდები + page access token-ები."""
    r = httpx.get(
        f"{_graph_base()}/me/accounts",
        params={"access_token": user_token, "fields": "id,name,access_token"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("data", [])


def subscribe_page(page_id: str, page_token: str) -> None:
    """გვერდს აწერს ჩვენს app-ს webhook-ზე (messages ველი)."""
    r = httpx.post(
        f"{_graph_base()}/{page_id}/subscribed_apps",
        params={"access_token": page_token, "subscribed_fields": "messages,messaging_postbacks"},
        timeout=15,
    )
    r.raise_for_status()


def get_page_instagram_account(page_id: str, page_token: str) -> str | None:
    """გვერდზე მიბმული Instagram Business ანგარიშის ID (თუ არსებობს)."""
    r = httpx.get(
        f"{_graph_base()}/{page_id}",
        params={"access_token": page_token, "fields": "instagram_business_account"},
        timeout=15,
    )
    r.raise_for_status()
    iba = r.json().get("instagram_business_account")
    return iba.get("id") if iba else None


# ---------------------------------------------------------------------------
# Send API
# ---------------------------------------------------------------------------
def send_text_message(page_token: str, recipient_id: str, text: str) -> None:
    r = httpx.post(
        f"{_graph_base()}/me/messages",
        params={"access_token": page_token},
        json={
            "recipient": {"id": recipient_id},
            "messaging_type": "RESPONSE",
            "message": {"text": text},
        },
        timeout=20,
    )
    r.raise_for_status()
