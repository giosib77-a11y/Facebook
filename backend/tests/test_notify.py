"""services/notify.py (Stage 20, A-038 / N-07): SMTP email, Telegram, throttle.

Offline: SMTP — fake ობიექტი `notify._smtp_connect`-ის ადგილას (ან fake `smtplib.SMTP` / `SMTP_SSL`
კლასები რეალური `_smtp_connect`-ისთვის); Telegram — `httpx.MockTransport`; DB / Auth — fake.
"""
import json
import logging
import smtplib
import ssl
from types import SimpleNamespace

import httpx
import pytest

from app.config import get_settings
from app.services import notify
from tests.conftest import FakeSupabase

# conftest-ის autouse guard `notify._smtp_connect`-ს ცვლის; რეალურს აქ ვინახავთ
_REAL_SMTP_CONNECT = notify._smtp_connect

PASSWORD = "s3cret-pass-XYZ"
OWNER_EMAIL = "owner.private@example.test"
TOKEN = "123456:TELEGRAM-SECRET-TOKEN"
SMTP_HOST = "smtp.example.test"


def _settings(monkeypatch, **update):
    s = get_settings().model_copy(update=update)
    monkeypatch.setattr(notify, "get_settings", lambda: s)
    return s


def _email_on(monkeypatch, **extra):
    return _settings(
        monkeypatch,
        smtp_host=SMTP_HOST, smtp_port=587, smtp_user="smtp-user", smtp_password=PASSWORD,
        notify_email_from="bot@example.test", **extra,
    )


def _telegram_on(monkeypatch):
    return _settings(monkeypatch, telegram_bot_token=TOKEN, telegram_chat_id="-1001")


class FakeSMTP:
    """context manager, რომელიც ყველა ბრძანებას ჩანაწერში წერს."""

    def __init__(self, fail_login=None, fail_send=None):
        self.events: list[tuple] = []
        self.sent: list = []
        self._fail_login, self._fail_send = fail_login, fail_send

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.events.append(("quit",))
        return False

    def login(self, user, password):
        self.events.append(("login", user, password))
        if self._fail_login:
            raise self._fail_login

    def send_message(self, msg):
        self.events.append(("send_message",))
        if self._fail_send:
            raise self._fail_send
        self.sent.append(msg)


def _install_smtp(monkeypatch, smtp=None):
    smtp = smtp or FakeSMTP()
    calls = []

    def _connect(host, port, timeout):
        calls.append((host, port, timeout))
        return smtp

    monkeypatch.setattr(notify, "_smtp_connect", _connect)
    return smtp, calls


def _install_http(monkeypatch, status=200, exc=None):
    requests = []

    def handler(request):
        requests.append(request)
        if exc is not None:
            raise exc(f"cannot connect to {request.url}")
        return httpx.Response(status)

    monkeypatch.setattr(notify, "_TRANSPORT", httpx.MockTransport(handler))
    return requests


class _Admin:
    def __init__(self, email=OWNER_EMAIL, error=None):
        self._email, self._error = email, error
        self.asked: list = []

    def get_user_by_id(self, owner_id):
        self.asked.append(owner_id)
        if self._error:
            raise self._error
        return SimpleNamespace(user=SimpleNamespace(email=self._email))


class FakeSC(FakeSupabase):
    def __init__(self, email=OWNER_EMAIL, error=None):
        super().__init__()
        self.admin = _Admin(email, error)
        self.auth = SimpleNamespace(admin=self.admin)


SHOP = {"id": "shop-1", "name": "Test Shop", "owner_id": "owner-1"}


def _service_client(monkeypatch, **kw):
    sc = FakeSC(**kw)
    sc.responses[("shops", "select")] = [{"name": "Test Shop", "owner_id": "owner-1", "currency": "GEL"}]
    monkeypatch.setattr(notify, "get_service_client", lambda: sc)
    return sc


# ---------------------------------------------------------------- send_email


@pytest.mark.parametrize("blank", ["smtp_host", "smtp_user", "smtp_password", "notify_email_from"])
def test_send_email_disabled_when_any_smtp_setting_blank(monkeypatch, blank):
    full = {"smtp_host": SMTP_HOST, "smtp_user": "u", "smtp_password": "p", "notify_email_from": "a@b.test"}
    _settings(monkeypatch, **{**full, blank: ""})
    smtp, calls = _install_smtp(monkeypatch)
    assert notify.send_email(OWNER_EMAIL, "s", "t") is False
    assert calls == [] and smtp.events == []


def test_send_email_blank_recipient_makes_no_connection(monkeypatch):
    _email_on(monkeypatch)
    smtp, calls = _install_smtp(monkeypatch)
    assert notify.send_email("  ", "s", "t") is False
    assert notify.send_email("", "s", "t") is False
    assert calls == []


def test_send_email_success_message_and_login(monkeypatch):
    _email_on(monkeypatch)
    smtp, calls = _install_smtp(monkeypatch)
    assert notify.send_email(OWNER_EMAIL, "ახალი შეკვეთა — Shop", "მაღაზია: Shop\nჯამი: 12 GEL") is True
    assert calls == [(SMTP_HOST, 587, 10)]
    assert ("login", "smtp-user", PASSWORD) in smtp.events
    msg = smtp.sent[0]
    assert msg["From"] == "bot@example.test"
    assert msg["To"] == OWNER_EMAIL
    assert msg["Subject"] == "ახალი შეკვეთა — Shop"
    assert "ჯამი: 12 GEL" in msg.get_content()
    assert msg.get_content_type() == "text/plain"
    assert msg.get_content_charset() == "utf-8"


def test_send_email_subject_crlf_cannot_inject_headers(monkeypatch):
    _email_on(monkeypatch)
    smtp, _ = _install_smtp(monkeypatch)
    assert notify.send_email(OWNER_EMAIL, "Hi\r\nBcc: evil@example.test", "t") is True
    msg = smtp.sent[0]
    assert msg["Bcc"] is None
    assert "\r" not in msg["Subject"] and "\n" not in msg["Subject"]
    assert "Bcc: evil@example.test" in msg["Subject"]  # ტექსტად დარჩა, header-ად არა


@pytest.mark.parametrize(
    "error",
    [
        smtplib.SMTPAuthenticationError(535, f"bad credentials {PASSWORD} for {OWNER_EMAIL}".encode()),
        OSError(f"cannot reach {SMTP_HOST} {OWNER_EMAIL}"),
        smtplib.SMTPRecipientsRefused({OWNER_EMAIL: (550, b"no such user")}),
    ],
)
def test_send_email_failure_returns_false_and_logs_class_only(monkeypatch, caplog, error):
    _email_on(monkeypatch)
    _install_smtp(monkeypatch, FakeSMTP(fail_login=error))
    with caplog.at_level(logging.WARNING, logger="app"):
        assert notify.send_email(OWNER_EMAIL, "s", "t") is False
    assert f"email send failed ({type(error).__name__})" in caplog.text
    for secret in (PASSWORD, OWNER_EMAIL, SMTP_HOST, "bad credentials", "no such user", "smtp-user"):
        assert secret not in caplog.text


def test_send_email_send_message_failure_returns_false(monkeypatch, caplog):
    _email_on(monkeypatch)
    _install_smtp(monkeypatch, FakeSMTP(fail_send=smtplib.SMTPServerDisconnected("gone")))
    with caplog.at_level(logging.WARNING, logger="app"):
        assert notify.send_email(OWNER_EMAIL, "s", "t") is False
    assert "SMTPServerDisconnected" in caplog.text


def test_send_email_connect_failure_returns_false(monkeypatch, caplog):
    # conftest-ის guard-ის ქცევა: _smtp_connect აგდებს OSError-ს → False
    _email_on(monkeypatch)
    blocked_calls = []

    def _boom(host, port, timeout):
        blocked_calls.append(host)
        raise TimeoutError(f"timed out {SMTP_HOST}")

    monkeypatch.setattr(notify, "_smtp_connect", _boom)
    with caplog.at_level(logging.WARNING, logger="app"):
        assert notify.send_email(OWNER_EMAIL, "s", "t") is False
    assert blocked_calls == [SMTP_HOST]
    assert "TimeoutError" in caplog.text and SMTP_HOST not in caplog.text


# ---------------------------------------------------------------- _smtp_connect (real function)


class _FakeSMTPClass:
    instances: list = []
    starttls_error: Exception | None = None

    def __init__(self, host, port, timeout=None, **kw):
        self.host, self.port, self.timeout, self.kw = host, port, timeout, kw
        self.events: list = []
        self.closed = False
        type(self).instances.append(self)

    def ehlo(self):
        self.events.append("ehlo")

    def starttls(self, context=None):
        self.events.append("starttls")
        self.context = context
        if type(self).starttls_error:
            raise type(self).starttls_error

    def close(self):
        self.closed = True


class _FakeSSLClass(_FakeSMTPClass):
    instances: list = []


def _patch_smtplib(monkeypatch, starttls_error=None):
    _FakeSMTPClass.instances = []
    _FakeSMTPClass.starttls_error = starttls_error
    _FakeSSLClass.instances = []
    monkeypatch.setattr(notify.smtplib, "SMTP", _FakeSMTPClass)
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", _FakeSSLClass)


def test_real_connect_587_uses_starttls_with_verifying_context(monkeypatch):
    _patch_smtplib(monkeypatch)
    server = _REAL_SMTP_CONNECT(SMTP_HOST, 587, 10)
    assert server is _FakeSMTPClass.instances[0]
    assert server.events == ["ehlo", "starttls", "ehlo"]
    assert (server.host, server.port, server.timeout) == (SMTP_HOST, 587, 10)
    assert server.context.verify_mode == ssl.CERT_REQUIRED and server.context.check_hostname
    assert _FakeSSLClass.instances == []


def test_real_connect_465_uses_ssl_without_starttls(monkeypatch):
    _patch_smtplib(monkeypatch)
    server = _REAL_SMTP_CONNECT(SMTP_HOST, 465, 10)
    assert server is _FakeSSLClass.instances[0]
    assert "starttls" not in server.events
    assert server.kw["context"].check_hostname
    assert _FakeSMTPClass.instances == []


def test_real_connect_starttls_failure_raises_and_closes(monkeypatch):
    _patch_smtplib(monkeypatch, starttls_error=smtplib.SMTPNotSupportedError("no starttls"))
    with pytest.raises(smtplib.SMTPNotSupportedError):
        _REAL_SMTP_CONNECT(SMTP_HOST, 587, 10)
    assert _FakeSMTPClass.instances[0].closed is True


def test_starttls_failure_never_sends_or_logs_in(monkeypatch, caplog):
    """send_email + რეალური _smtp_connect: STARTTLS ჩავარდა → login / send_message არ გამოიძახება."""
    _email_on(monkeypatch)
    _patch_smtplib(monkeypatch, starttls_error=smtplib.SMTPNotSupportedError("no starttls"))
    monkeypatch.setattr(notify, "_smtp_connect", _REAL_SMTP_CONNECT)
    sent = []
    _FakeSMTPClass.login = lambda self, *a: sent.append("login")
    _FakeSMTPClass.send_message = lambda self, *a: sent.append("send")
    try:
        with caplog.at_level(logging.WARNING, logger="app"):
            assert notify.send_email(OWNER_EMAIL, "s", "t") is False
    finally:
        del _FakeSMTPClass.login, _FakeSMTPClass.send_message
    assert sent == []
    assert "SMTPNotSupportedError" in caplog.text


# ---------------------------------------------------------------- send_telegram


def test_send_telegram_disabled_makes_no_request(monkeypatch):
    _settings(monkeypatch, telegram_bot_token="", telegram_chat_id="-1001")
    requests = _install_http(monkeypatch)
    assert notify.send_telegram("hi") is False
    _settings(monkeypatch, telegram_bot_token=TOKEN, telegram_chat_id="")
    assert notify.send_telegram("hi") is False
    assert requests == []


def test_send_telegram_request_shape(monkeypatch):
    _telegram_on(monkeypatch)
    requests = _install_http(monkeypatch, status=200)
    assert notify.send_telegram("გამარჯობა") is True
    req = requests[0]
    assert req.method == "POST"
    assert req.url.host == "api.telegram.org"
    assert req.url.path == f"/bot{TOKEN}/sendMessage"
    assert json.loads(req.content) == {
        "chat_id": "-1001", "text": "გამარჯობა", "disable_web_page_preview": True,
    }


def test_send_telegram_non_2xx_logs_status_only(monkeypatch, caplog):
    _telegram_on(monkeypatch)
    _install_http(monkeypatch, status=401)
    with caplog.at_level(logging.WARNING, logger="app"):
        assert notify.send_telegram("hi") is False
    assert "telegram send failed (HTTP 401)" in caplog.text
    assert TOKEN not in caplog.text


def test_send_telegram_connect_error_with_url_in_text_does_not_leak_token(monkeypatch, caplog):
    _telegram_on(monkeypatch)
    _install_http(monkeypatch, exc=httpx.ConnectError)
    with caplog.at_level(logging.DEBUG):
        assert notify.send_telegram("hi") is False
    assert "telegram send failed (ConnectError)" in caplog.text
    assert TOKEN not in caplog.text and "api.telegram.org" not in caplog.text


# ---------------------------------------------------------------- throttle


def test_allow_interval_and_keys(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(notify, "time", SimpleNamespace(monotonic=lambda: now[0]))
    assert notify._allow(("k", 1), 60) is True
    now[0] += 59
    assert notify._allow(("k", 1), 60) is False
    assert notify._allow(("k", 2), 60) is True  # სხვა გასაღები
    now[0] += 2
    assert notify._allow(("k", 1), 60) is True  # ინტერვალი გავიდა


def test_allow_works_at_monotonic_zero(monkeypatch):
    monkeypatch.setattr(notify, "time", SimpleNamespace(monotonic=lambda: 0.0))
    assert notify._allow(("k",), 60) is True
    assert notify._allow(("k",), 60) is False


def test_allow_prunes_keys_older_than_24h(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(notify, "time", SimpleNamespace(monotonic=lambda: now[0]))
    notify._allow(("old",), 60)
    now[0] += 24 * 3600 + 1
    notify._allow(("new",), 60)
    assert ("old",) not in notify._THROTTLE and ("new",) in notify._THROTTLE


# ---------------------------------------------------------------- owner_email


def test_owner_email_returns_address():
    sc = FakeSC(email="a@b.test")
    assert notify.owner_email(sc, "owner-1") == "a@b.test"
    assert sc.admin.asked == ["owner-1"]


def test_owner_email_failure_returns_none_and_logs_class(caplog):
    sc = FakeSC(error=RuntimeError(f"auth down {OWNER_EMAIL}"))
    with caplog.at_level(logging.WARNING, logger="app"):
        assert notify.owner_email(sc, "owner-1") is None
    assert "RuntimeError" in caplog.text and OWNER_EMAIL not in caplog.text


# ---------------------------------------------------------------- notify_new_order


def test_new_order_disabled_touches_neither_db_nor_smtp(monkeypatch):
    _settings(monkeypatch, smtp_host="")
    smtp, calls = _install_smtp(monkeypatch)

    def _no_db():
        raise AssertionError("DB must not be touched when email is disabled")

    monkeypatch.setattr(notify, "get_service_client", _no_db)
    notify.notify_new_order("shop-1", "order-1", 10)
    assert calls == []


def test_new_order_sends_email_without_customer_data(monkeypatch):
    _email_on(monkeypatch, public_base_url="https://app.example.test/")
    sc = _service_client(monkeypatch)
    smtp, calls = _install_smtp(monkeypatch)
    notify.notify_new_order("shop-1", "order-1", "45.50")
    assert len(calls) == 1
    msg = smtp.sent[0]
    assert msg["To"] == OWNER_EMAIL
    assert msg["Subject"] == "ახალი შეკვეთა — Test Shop"
    body = msg.get_content()
    assert "Test Shop" in body and "45.50 GEL" in body
    assert "https://app.example.test/panel/" in body
    assert sc.admin.asked == ["owner-1"]
    shop_query = sc.calls_for("shops", "select")[0]
    assert ("eq", "id", "shop-1") in shop_query.filters
    # order_id-ც კი არ არის საჭირო body-ში; clientის ველები კი — არასდროს
    assert "order-1" not in body


def test_new_order_without_public_base_url_has_no_panel_link(monkeypatch):
    _email_on(monkeypatch, public_base_url="")
    _service_client(monkeypatch)
    smtp, _ = _install_smtp(monkeypatch)
    notify.notify_new_order("shop-1", "order-1", 10)
    assert "/panel/" not in smtp.sent[0].get_content()


def test_new_order_throttled_per_shop(monkeypatch):
    _email_on(monkeypatch)
    _service_client(monkeypatch)
    smtp, calls = _install_smtp(monkeypatch)
    notify.notify_new_order("shop-1", "o1", 10)
    notify.notify_new_order("shop-1", "o2", 11)
    assert len(calls) == 1
    notify.notify_new_order("shop-2", "o3", 12)
    assert len(calls) == 2


def test_new_order_owner_email_failure_sends_nothing(monkeypatch, caplog):
    _email_on(monkeypatch)
    _service_client(monkeypatch, error=RuntimeError("auth down"))
    smtp, calls = _install_smtp(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="app"):
        notify.notify_new_order("shop-1", "o1", 10)
    assert calls == []
    assert "RuntimeError" in caplog.text


def test_new_order_shop_not_found_sends_nothing(monkeypatch):
    _email_on(monkeypatch)
    sc = _service_client(monkeypatch)
    sc.responses[("shops", "select")] = []
    _, calls = _install_smtp(monkeypatch)
    notify.notify_new_order("shop-1", "o1", 10)
    assert calls == []


def test_new_order_db_error_never_raises(monkeypatch, caplog):
    _email_on(monkeypatch)
    sc = _service_client(monkeypatch)
    sc.errors[("shops", "select")] = ConnectionError("db down")
    _, calls = _install_smtp(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="app"):
        notify.notify_new_order("shop-1", "o1", 10)
    assert calls == [] and "ConnectionError" in caplog.text


def test_new_order_smtp_failure_never_raises(monkeypatch):
    _email_on(monkeypatch)
    _service_client(monkeypatch)
    _install_smtp(monkeypatch, FakeSMTP(fail_login=smtplib.SMTPAuthenticationError(535, b"x")))
    notify.notify_new_order("shop-1", "o1", 10)  # არ ვარდება


# ---------------------------------------------------------------- notify_handoff


def test_handoff_disabled_makes_no_lookup(monkeypatch):
    _settings(monkeypatch, smtp_host="")
    sc = FakeSC()
    _, calls = _install_smtp(monkeypatch)
    notify.notify_handoff(sc, SHOP)
    assert calls == [] and sc.admin.asked == [] and sc.calls == []


def test_handoff_sends_email_without_customer_data(monkeypatch):
    _email_on(monkeypatch)
    sc = FakeSC()
    smtp, calls = _install_smtp(monkeypatch)
    shop = {**SHOP, "psid": "PSID-123", "last_message": "ჩემი ტელეფონი 555"}
    notify.notify_handoff(sc, shop)
    assert len(calls) == 1
    msg = smtp.sent[0]
    assert msg["Subject"] == "კლიენტს ოპერატორი სჭირდება — Test Shop"
    body = msg.get_content()
    assert "Test Shop" in body
    assert "PSID-123" not in body and "555" not in body


def test_handoff_throttled_per_shop_10_minutes(monkeypatch):
    _email_on(monkeypatch)
    now = [100.0]
    monkeypatch.setattr(notify, "time", SimpleNamespace(monotonic=lambda: now[0]))
    sc = FakeSC()
    _, calls = _install_smtp(monkeypatch)
    notify.notify_handoff(sc, SHOP)
    notify.notify_handoff(sc, SHOP)
    assert len(calls) == 1
    notify.notify_handoff(sc, {**SHOP, "id": "shop-2"})
    assert len(calls) == 2
    now[0] += 601
    notify.notify_handoff(sc, SHOP)
    assert len(calls) == 3


def test_handoff_owner_email_failure_sends_nothing(monkeypatch):
    _email_on(monkeypatch)
    sc = FakeSC(error=RuntimeError("auth down"))
    _, calls = _install_smtp(monkeypatch)
    notify.notify_handoff(sc, SHOP)
    assert calls == []


def test_handoff_bad_shop_never_raises(monkeypatch):
    _email_on(monkeypatch)
    _install_smtp(monkeypatch)
    notify.notify_handoff(FakeSC(), None)  # shop.get → AttributeError → catch-all


# ---------------------------------------------------------------- alert_bot_down


def test_alert_bot_down_disabled_makes_no_request(monkeypatch):
    _settings(monkeypatch, telegram_bot_token="")
    requests = _install_http(monkeypatch)
    notify.alert_bot_down(SHOP, "token_expired")
    assert requests == []


def test_alert_bot_down_text_and_throttle_per_kind(monkeypatch):
    _telegram_on(monkeypatch)
    requests = _install_http(monkeypatch)
    notify.alert_bot_down(SHOP, "token_expired")
    notify.alert_bot_down(SHOP, "token_expired")
    assert len(requests) == 1
    notify.alert_bot_down(SHOP, "send_failed")
    assert len(requests) == 2
    assert json.loads(requests[0].content)["text"] == "⚠️ BOT DOWN (token_expired) — shop shop-1 „Test Shop“"


def test_alert_bot_down_repeats_after_six_hours(monkeypatch):
    _telegram_on(monkeypatch)
    now = [50.0]
    monkeypatch.setattr(notify, "time", SimpleNamespace(monotonic=lambda: now[0]))
    requests = _install_http(monkeypatch)
    notify.alert_bot_down(SHOP, "k")
    now[0] += 6 * 3600 - 1
    notify.alert_bot_down(SHOP, "k")
    assert len(requests) == 1
    now[0] += 2
    notify.alert_bot_down(SHOP, "k")
    assert len(requests) == 2


def test_alert_bot_down_transport_error_never_raises(monkeypatch, caplog):
    _telegram_on(monkeypatch)
    _install_http(monkeypatch, exc=httpx.ReadTimeout)
    with caplog.at_level(logging.WARNING, logger="app"):
        notify.alert_bot_down(SHOP, "k")
    assert TOKEN not in caplog.text


def test_public_functions_never_raise_when_handler_blows_up(monkeypatch):
    """settings-ის წაკითხვაც კი რომ ჩავარდეს — არცერთი public ფუნქცია არ აგდებს."""
    def _boom():
        raise RuntimeError("settings broken")

    monkeypatch.setattr(notify, "get_settings", _boom)
    assert notify.send_email("a@b.test", "s", "t") is False
    assert notify.send_telegram("t") is False
    notify.notify_new_order("s", "o", 1)
    notify.notify_handoff(FakeSC(), SHOP)
    notify.alert_bot_down(SHOP, "k")
