"""Supabase access token-ის ლოკალური შემოწმება (Stage 22, A-046 / N-10).

`verify(token)` სამიდან ერთ-ერთს აბრუნებს:
  - dict   — token ლოკალურად დადასტურდა (ხელმოწერა JWKS-ის გასაღებით, `exp`, `aud`, `iss`, `sub`);
             ეს არის claims;
  - None   — ლოკალურად ვერ წყდება (HS256, `kid`-ის გარეშე, უცნობი `kid`, JWKS მიუწვდომელია,
             ლოკალური შემოწმება გამორთულია) -> გამომძახებელმა უნდა გამოიყენოს ძველი ქსელური
             `auth.get_user` (ავტორიტეტული გზა; ამ მოდულში არასდროს ვიღებთ token-ს შემოწმების გარეშე);
  - raise InvalidToken — token ცხადად არასწორია (ცუდი ხელმოწერა / ვადა / aud / iss / alg) -> 401,
             fallback-ის გარეშე.
არასდროს ვაბრუნებთ InvalidToken-ს მხოლოდ იმიტომ, რომ JWKS მიუწვდომელია.

ლოგში token / `sub` / email / მომხმარებლის მიერ მოცემული `kid` არასდროს ხვდება
(`alg` და JWKS-ში ნაპოვნი `kid` საჯაროა).
"""
import logging
import threading
import time
from typing import Any

import jwt

from app.config import get_settings

logger = logging.getLogger("app")

ASYMMETRIC = frozenset({"ES256", "RS256"})
LEEWAY_SECONDS = 30
JWKS_LIFESPAN_SECONDS = 300  # Supabase: JWKS-ის cache <= ~10 წთ
JWKS_TIMEOUT_SECONDS = 5
REFRESH_MIN_INTERVAL_SECONDS = 60  # უცნობ kid-ზე იძულებითი refresh არაუმეტეს 1-ჯერ / 60 წმ
JWKS_ERROR_BACKOFF_SECONDS = 30  # JWKS-ის შეცდომის შემდეგ ამ ხნით ქსელს აღარ ვცდით (ყოველ მოთხოვნაზე 5 წმ timeout არა)
_UNKNOWN_KID_LOG_INTERVAL = 60
_JWKS_ERROR_LOG_INTERVAL = 300
_AUDIENCE = "authenticated"


class InvalidToken(Exception):
    """token ცხადად არასწორია (-> 401); ტექსტი არასდროს შეიცავს token-ს."""


_lock = threading.Lock()
_jwks_client: jwt.PyJWKClient | None = None
_jwks_url: str | None = None
_last_refresh: float | None = None
_last_jwks_error: float | None = None
_last_logged: dict[str, float] = {}
_active_logged = False


def _monotonic() -> float:
    return time.monotonic()


def _reset_for_tests() -> None:
    global _jwks_client, _jwks_url, _last_refresh, _last_jwks_error, _active_logged
    with _lock:
        _jwks_client = None
        _jwks_url = None
        _last_refresh = None
        _last_jwks_error = None
        _active_logged = False
        _last_logged.clear()


def _client() -> jwt.PyJWKClient:
    """module-level PyJWKClient (JWKS cache პროცესში საერთოა); SUPABASE_URL-ის შეცვლაზე ახლდება."""
    global _jwks_client, _jwks_url, _last_refresh, _last_jwks_error
    url = f"{get_settings().supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    with _lock:
        if _jwks_client is None or _jwks_url != url:
            _jwks_client = jwt.PyJWKClient(
                url,
                cache_jwk_set=True,
                lifespan=JWKS_LIFESPAN_SECONDS,
                timeout=JWKS_TIMEOUT_SECONDS,
                headers={"User-Agent": "ChatAssist-backend"},
            )
            _jwks_url = url
            _last_refresh = None
            _last_jwks_error = None
        return _jwks_client


def _log_limited(key: str, interval: float, level: int, msg: str, *args: Any) -> None:
    now = _monotonic()
    with _lock:
        last = _last_logged.get(key)
        if last is not None and now - last < interval:
            return
        _last_logged[key] = now
    logger.log(level, msg, *args)


def _jwks_failed(exc: BaseException) -> None:
    global _last_jwks_error
    with _lock:
        _last_jwks_error = _monotonic()
    # მხოლოდ კლასი: exception-ის ტექსტი URL-ს / პასუხის ნაწილს შეიძლება შეიცავდეს
    _log_limited("jwks_error", _JWKS_ERROR_LOG_INTERVAL, logging.WARNING,
                 "jwt: JWKS unavailable (%s) - falling back to Auth server", type(exc).__name__)


def _find_key(client: jwt.PyJWKClient, kid: str) -> jwt.PyJWK | None:
    """გასაღები `kid`-ით: cache-იდან; უცნობზე არაუმეტეს 1 იძულებითი refresh / 60 წმ. JWKS-ის შეცდომა ავრცელებს exception-ს."""
    global _last_refresh

    def lookup(jwk_set: jwt.PyJWKSet) -> jwt.PyJWK | None:
        return next((k for k in jwk_set.keys if k.key_id == kid), None)

    key = lookup(client.get_jwk_set())
    if key is not None:
        return key
    with _lock:
        now = _monotonic()
        refresh = _last_refresh is None or now - _last_refresh >= REFRESH_MIN_INTERVAL_SECONDS
        if refresh:
            _last_refresh = now  # შეცდომის შემთხვევაშიც: JWKS-ზე მოთხოვნები შემოსაზღვრულია
    if refresh:
        key = lookup(client.get_jwk_set(refresh=True))
    return key


def verify(token: str) -> dict | None:
    """იხ. მოდულის docstring. InvalidToken ან dict ან None."""
    global _active_logged
    settings = get_settings()
    if not settings.jwt_local_verify or not settings.supabase_url:
        return None

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise InvalidToken("malformed token") from None

    alg = header.get("alg")
    if alg == "HS256":
        # legacy secret JWKS-ში არ ქვეყნდება (kid-ის მიუხედავად) -> Auth server
        return None
    if not isinstance(alg, str) or alg not in ASYMMETRIC:
        raise InvalidToken("unsupported alg")  # none, HS384/512, ES384/512, PS*, არ არის

    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        return None

    with _lock:
        in_backoff = (_last_jwks_error is not None
                      and _monotonic() - _last_jwks_error < JWKS_ERROR_BACKOFF_SECONDS)
    if in_backoff:
        return None

    try:
        key = _find_key(_client(), kid)
    except Exception as exc:  # ნებისმიერი JWKS-ის პრობლემა = Auth server, არასდროს 401
        _jwks_failed(exc)
        return None
    if key is None:
        # kid მომხმარებლის შეყვანაა -> ლოგში არ ვწერთ
        _log_limited("unknown_kid", _UNKNOWN_KID_LOG_INTERVAL, logging.INFO,
                     "jwt: token kid not in JWKS - falling back to Auth server")
        return None

    # alg confusion: JWK-ის ალგორითმი უნდა ემთხვეოდეს header-ს, გასაღები - მხოლოდ ხელმოწერისთვის
    if key.algorithm_name != alg or key.public_key_use not in (None, "sig"):
        raise InvalidToken("key does not match token alg")

    try:
        claims = jwt.decode(
            token,
            key.key,
            algorithms=[alg],
            audience=_AUDIENCE,
            issuer=f"{settings.supabase_url.rstrip('/')}/auth/v1",
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
    except jwt.InvalidTokenError:
        raise InvalidToken("token rejected") from None
    except jwt.PyJWTError as exc:  # მაგ. InvalidKeyError - JWKS-ის გასაღები გატეხილია, token-ის ბრალი არ არის
        _jwks_failed(exc)
        return None

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise InvalidToken("invalid sub")

    with _lock:
        first = not _active_logged
        _active_logged = True
    if first:
        logger.info("jwt: local verification active (alg=%s, kid=%s)", alg, kid)
    return claims


def unverified_claims(token: str) -> dict:
    """token-ის claims ხელმოწერის შემოწმების გარეშე.

    გამოიყენე მხოლოდ იმავე token-ის წარმატებული ქსელური `get_user`-ის შემდეგ
    (Auth-მა ხელმოწერა უკვე დაადასტურა). ნებისმიერ შეცდომაზე `{}`.
    """
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return {}
    return claims if isinstance(claims, dict) else {}
