"""Facebook Graph API ჰელპერები — ხელმოწერა, OAuth, Send API, state.

Send API + OAuth ცოცხალ Meta App-ს მოითხოვს; ხელმოწერისა და state-ის ლოგიკა
offline-ად ტესტირებადია.
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
from urllib.parse import urlparse

import httpx

from app.config import get_settings

logger = logging.getLogger("app")

# ---- OAuth scope: Messenger + Instagram-ისთვის საჭირო ნებართვები ----
# Instagram (Facebook-login path): აპში დამატებულია instagram_basic +
# instagram_manage_messages ("Add required messaging permissions"). webhook.py
# ამუშავებს object=="instagram"-ს. რეალურ IG-კლიენტებთან — App Review სჭირდება.
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


def _b64url_decode(s: str) -> bytes:
    """base64url პადინგის დამატებით (Meta signed_request-ს პადინგი აკლია)."""
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode())


def parse_signed_request(signed_request: str, app_secret: str) -> dict | None:
    """Meta-ს `signed_request`-ის ვერიფიკაცია/გახსნა (Data Deletion callback-ისთვის).

    ფორმატი: "<base64url_signature>.<base64url_payload>". ხელმოწერა = HMAC-SHA256
    payload-ის (base64url სტრიქონის) app_secret-ით. აბრუნებს payload dict-ს
    ან None თუ ფორმატი/ხელმოწერა არასწორია.
    """
    if not signed_request or "." not in signed_request:
        return None
    try:
        encoded_sig, payload = signed_request.split(".", 1)
        sig = _b64url_decode(encoded_sig)
        data = json.loads(_b64url_decode(payload))
    except Exception:
        return None
    expected = hmac.new(app_secret.encode(), payload.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, sig):
        return None
    return data


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
        "response_type": "code",
        "state": state,
    }
    if s.fb_login_config_id:
        # Facebook Login for Business — config-based (business-owned გვერდები/assets).
        # ნებართვები/აქტივები კონფიგში განისაზღვრება, არა scope-ით.
        params["config_id"] = s.fb_login_config_id
    else:
        # კლასიკური scope-based (პირადი პროფილის გვერდები)
        params["scope"] = OAUTH_SCOPES
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


def get_user_id(user_token: str) -> str | None:
    """დამაკავშირებელი Facebook მომხმარებლის app-scoped ID (Data Deletion callback-ისთვის)."""
    r = httpx.get(
        f"{_graph_base()}/me",
        params={"access_token": user_token, "fields": "id"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("id")


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


# ---------------------------------------------------------------------------
# შემოსული სურათის ჩამოტვირთვა (Gemini multimodal-ისთვის)
# ---------------------------------------------------------------------------
# დაშვებული სქემები — file://, gopher://, ftp:// და სხვა SSRF-ვექტორები იკეტება
_ALLOWED_SCHEMES = ("http", "https")
# რამდენ redirect-ს ვყვებით ხელით (თითოეული მისამართი ცალკე მოწმდება)
_MAX_REDIRECTS = 3


def _is_public_http_url(url: str) -> bool:
    """True — თუ URL საჯარო ინტერნეტ-მისამართზე მიუთითებს.

    ⚠️ SSRF-ის დაცვა. `products.image_url`-ს გამყიდველი თავად წერს, ე.ი. ეს
    მისამართი არასანდოა. შიდა/ლოკალური მისამართები (127.x, 10.x, 192.168.x,
    169.254.169.254 = cloud metadata) იბლოკება, თორემ სერვერი მათ ჩამოტვირთავდა
    და შიგთავსს Gemini-ს გადასცემდა.
    """
    try:
        parsed = urlparse(url or "")
    except Exception:
        return False
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except (socket.gaierror, UnicodeError, ValueError):
        return False
    if not infos:
        return False
    # ყველა გარჩეული მისამართი უნდა იყოს საჯარო (თუნდაც ერთი შიდა — ვბლოკავთ)
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            return False
    return True


def download_image(
    url: str, max_bytes: int = 8 * 1024 * 1024, timeout: float = 20
) -> tuple[bytes, str] | None:
    """სურათის ჩამოტვირთვა URL-იდან (კლიენტის FB/IG CDN ან პროდუქტის Storage).

    აბრუნებს (bytes, mime_type) ან None (თუ ვერ ჩამოიტვირთა / არ არის სურათი /
    ძალიან დიდია / მისამართი არასაჯაროა). ბოტი უსურათოდ მაინც აგრძელებს.

    ⚠️ ორი დაცვა (რევიუ P1-1):
      1. SSRF — ყოველი მისამართი (redirect-ებიც) მოწმდება `_is_public_http_url`-ით.
      2. მეხსიერება — ნაკადურად (stream) ვკითხულობთ და ჭერზე ვწყვეტთ, რომ
         უზარმაზარმა პასუხმა instance არ ჩააგდოს (ადრე `r.content` ჯერ
         მთლიანად ჩამოტვირთავდა და მერე ამოწმებდა ზომას).
    """
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        if not _is_public_http_url(current):
            logger.warning("სურათის ჩამოტვირთვა დაიბლოკა (არასაჯარო მისამართი): %.120s", current)
            return None
        with httpx.stream(
            "GET", current, timeout=timeout, follow_redirects=False
        ) as r:
            if r.is_redirect:
                nxt = r.headers.get("location")
                if not nxt:
                    return None
                current = str(httpx.URL(current).join(nxt))
                continue
            r.raise_for_status()
            # Content-Length-ს ვენდობით მხოლოდ ადრეული უარისთვის — ნამდვილი
            # ჭერი ქვემოთ, ნაკადის კითხვისასაა (ყალბი header არ გვატყუებს).
            declared = r.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                return None
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    logger.warning("სურათი ჭერს გადააჭარბა (%d ბაიტი) — შეწყდა", len(buf))
                    return None
            data = bytes(buf)
            if not data:
                return None
            mime = (r.headers.get("content-type") or "image/jpeg").split(";")[0].strip().lower()
            if not mime.startswith("image/"):
                mime = "image/jpeg"
            return data, mime
    logger.warning("სურათის ჩამოტვირთვა: ძალიან ბევრი redirect")
    return None
