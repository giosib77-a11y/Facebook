"""შეტყობინებები მფლობელს (Stage 20, A-038 / N-07): SMTP email + Telegram.

- email (მაღაზიის მფლობელს): ახალი შეკვეთა, კლიენტს ოპერატორი სჭირდება — stdlib `smtplib`,
  ნებისმიერი SMTP provider (`SMTP_HOST/PORT/USER/PASSWORD`, `NOTIFY_EMAIL_FROM`);
- Telegram (პლატფორმის ადმინს): BOT DOWN ალერტი — არსებული `httpx`.

⚠️ წესები:
  - ყველა public ფუნქცია **არასდროს** აგდებს: შეტყობინების ჩავარდნა მთავარ ნაკადს (შეკვეთა,
    webhook) არ აფუჭებს;
  - ლოგში მხოლოდ exception-ის **კლასის სახელი** — ტექსტი შეიძლება შეიცავდეს email მისამართს,
    SMTP სერვერის პასუხს ან Telegram token-ს (URL-ში); პაროლი / token / მისამართი — არასდროს;
  - email-ის გაგზავნა ბლოკირებადია → მხოლოდ ფონურ ნაკადში (BackgroundTasks / webhook background);
  - email-ში კლიენტის მონაცემი (psid, შეტყობინების ტექსტი, სახელი, ტელეფონი) არ ხვდება;
  - გამორთული არხი (env ცარიელია) = ჩუმი no-op, ქსელის / DB-ს გარეშე.
"""
import logging
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage

import httpx

from app.config import get_settings
from app.core.supabase_client import get_service_client

logger = logging.getLogger("app")

# ტესტებისთვის: httpx.MockTransport (production-ში None = ნამდვილი ქსელი); მხოლოდ Telegram
_TRANSPORT: httpx.BaseTransport | None = None

_SMTP_TIMEOUT = 10
_THROTTLE_TTL = 24 * 3600
# გასაღები → ბოლო დაშვების დრო (time.monotonic). პროცესის მეხსიერებაშია: რამდენიმე instance-ზე
# ლიმიტი instance-ზეა — შეტყობინებისთვის ეს საკმარისია (დუბლი არ არის კრიტიკული).
_THROTTLE: dict[tuple, float] = {}
_THROTTLE_LOCK = threading.Lock()


def _post(url: str, *, json: dict) -> httpx.Response:
    with httpx.Client(timeout=10, transport=_TRANSPORT) as client:
        return client.post(url, json=json)


def _smtp_connect(host: str, port: int, timeout: float) -> smtplib.SMTP:
    """დაშიფრული SMTP კავშირი: 465 → SSL; სხვა → STARTTLS. STARTTLS-ის ჩავარდნა = exception
    (დაუშიფრავად login / გაგზავნა არასდროს)."""
    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
    server = smtplib.SMTP(host, port, timeout=timeout)
    try:
        server.ehlo()
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
    except BaseException:
        try:
            server.close()
        except Exception:  # noqa: BLE001 — თავდაპირველი შეცდომა უფრო მნიშვნელოვანია
            pass
        raise
    return server


def _allow(key: tuple, interval: float) -> bool:
    """True, თუ ამ გასაღებზე ბოლო `interval` წამში დაშვება არ ყოფილა (და ახლა ვიწერთ)."""
    now = time.monotonic()
    with _THROTTLE_LOCK:
        for k in [k for k, t in _THROTTLE.items() if now - t > _THROTTLE_TTL]:
            del _THROTTLE[k]
        last = _THROTTLE.get(key)
        if last is not None and now - last < interval:
            return False
        _THROTTLE[key] = now
        return True


def send_email(to: str, subject: str, text: str) -> bool:
    """გაგზავნა SMTP-ით (ბლოკირებადი). გამორთული არხი / ცარიელი `to` → False, ქსელის გარეშე."""
    try:
        s = get_settings()
        if not s.email_notifications_enabled or not (to or "").strip():
            return False
        msg = EmailMessage()
        msg["From"] = s.notify_email_from
        msg["To"] = to.strip()
        # header injection: CR/LF subject-ში → space
        msg["Subject"] = " ".join(subject.replace("\r", " ").replace("\n", " ").split())
        msg.set_content(text, charset="utf-8")
        with _smtp_connect(s.smtp_host, s.smtp_port, _SMTP_TIMEOUT) as server:
            server.login(s.smtp_user, s.smtp_password)
            server.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001 — შეტყობინება მთავარ ნაკადს არ აფუჭებს
        logger.warning("email send failed (%s)", type(exc).__name__)
        return False


def send_telegram(text: str) -> bool:
    """Telegram-ის შეტყობინება ადმინის ჩატში. ⚠️ URL / exception-ის ტექსტი არასდროს ილოგება (token)."""
    try:
        s = get_settings()
        if not s.telegram_enabled:
            return False
        r = _post(
            f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
            json={"chat_id": s.telegram_chat_id, "text": text, "disable_web_page_preview": True},
        )
        if 200 <= r.status_code < 300:
            return True
        logger.warning("telegram send failed (HTTP %s)", r.status_code)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram send failed (%s)", type(exc).__name__)
        return False


def owner_email(sc, owner_id: str) -> str | None:
    """მფლობელის email Supabase Auth-იდან (admin API, service client). შეცდომა → None."""
    try:
        email = sc.auth.admin.get_user_by_id(owner_id).user.email
        return email or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("owner email lookup failed (%s)", type(exc).__name__)
        return None


def _panel_line() -> str:
    base = (get_settings().public_base_url or "").strip().rstrip("/")
    return f"\nპანელი: {base}/panel/\n" if base else ""


def notify_new_order(shop_id: str, order_id: str, total) -> None:
    """ახალი შეკვეთის email მფლობელს (BackgroundTask). კლიენტის მონაცემი არ იგზავნება."""
    try:
        if not get_settings().email_notifications_enabled:
            return
        if not _allow(("order", shop_id), 60):
            return
        sc = get_service_client()
        rows = (
            sc.table("shops").select("name,owner_id,currency").eq("id", shop_id).limit(1).execute().data
        )
        if not rows:
            return
        shop = rows[0]
        to = owner_email(sc, shop.get("owner_id"))
        if not to:
            return
        name = shop.get("name") or ""
        amount = f"{total} {shop.get('currency') or ''}".strip()
        text = f"მაღაზია: {name}\nახალი შეკვეთა: {amount}\n" + _panel_line()
        send_email(to, f"ახალი შეკვეთა — {name}", text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("new order notification failed (%s)", type(exc).__name__)


def notify_handoff(sc, shop: dict) -> None:
    """„კლიენტს ოპერატორი სჭირდება" email მფლობელს. psid / შეტყობინების ტექსტი არ იგზავნება."""
    try:
        if not get_settings().email_notifications_enabled:
            return
        if not _allow(("handoff", shop.get("id")), 600):
            return
        to = owner_email(sc, shop.get("owner_id"))
        if not to:
            return
        name = shop.get("name") or ""
        text = f"მაღაზია: {name}\nკლიენტს ოპერატორი სჭირდება — ბოტი საუბარს აპაუზებს.\n" + _panel_line()
        send_email(to, f"კლიენტს ოპერატორი სჭირდება — {name}", text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("handoff notification failed (%s)", type(exc).__name__)


def alert_bot_down(shop: dict, kind: str) -> None:
    """BOT DOWN ალერტი ადმინის Telegram-ში (კატეგორიაზე 6 სთ-ში ერთხელ)."""
    try:
        if not get_settings().telegram_enabled:
            return
        if not _allow(("down", shop.get("id"), kind), 6 * 3600):
            return
        send_telegram(f"⚠️ BOT DOWN ({kind}) — shop {shop.get('id')} „{shop.get('name') or ''}“")
    except Exception as exc:  # noqa: BLE001
        logger.warning("bot down alert failed (%s)", type(exc).__name__)
