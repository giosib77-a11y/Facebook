"""ავთენტიფიკაცია — Supabase access token-ის შემოწმება.

კლიენტი აგზავნის `Authorization: Bearer <supabase_access_token>`. `get_current_auth` სამიდან ერთ გზას გადის
(Stage 22, A-046 / N-10):
  1. ლოკალური — ES256/RS256 token მოწმდება JWKS-ის საჯარო გასაღებით (`core/jwt_verify`): ხელმოწერა, `exp`,
     `aud`, `iss`, `sub`. Auth server-ს არ ვმიმართავთ (`verified_by="local"`, claims ივსება).
  2. ქსელური — ლოკალურად ვერ წყდება (HS256, უცნობი `kid`, JWKS მიუწვდომელია, `JWT_LOCAL_VERIFY=false`):
     ძველი `auth.get_user(token)` (Supabase Auth API). `verified_by="network"`; claims — იმავე token-ის
     (Auth-ის მიერ უკვე დადასტურებული) ხელმოუწერელი წაკითხვა.
  3. 401 — token ცხადად არასწორია (ცუდი ხელმოწერა / ვადა / aud / iss / alg) ან Auth server-მა უარყო;
     fallback-ის გარეშე, `create_client`-მდე.
შემდეგ ვქმნით per-request Supabase კლიენტს anon/publishable key-ით და ვაყენებთ ამ token-ს PostgREST-ისთვის,
რათა ყველა DB-მოთხოვნა შესრულდეს ამ მომხმარებლის სახელით — ანუ RLS პოლისიები ავტომატურად მოქმედებენ.

რატომ არ არის tenant isolation ჩვენს შემოწმებაზე დამოკიდებული: PostgREST თავად ამოწმებს JWT-ს (ხელმოწერა, ვადა)
ყოველ RLS query-ზე, ამიტომ ყალბი ან ვადაგასული token ბაზიდან მონაცემს ვერ წაიკითხავს, ლოკალური შემოწმება
რაც უნდა მოხდეს. ლოკალური გზის ფასი: sign-out / ban / მომხმარებლის წაშლა token-ის `exp`-მდე (≤ 1 სთ) ძალაში
რჩება — ეს Accepted Risk-ია (PROJECT.md); ადმინისთვის არა: `confirm_with_auth_server` (იხ. `api/admin.py`).
"""
from dataclasses import dataclass, field

from fastapi import Header, HTTPException, status
from supabase import Client, create_client

from app.config import get_settings
from app.core import jwt_verify

_INVALID_TOKEN = "token არასწორია ან ვადაგასულია"


@dataclass
class CurrentAuth:
    """ერთი მოთხოვნის ავტორიზებული კონტექსტი."""
    user_id: str
    email: str | None
    client: Client  # JWT-ით ავტორიზებული Supabase კლიენტი (RLS მოქმედებს)
    # token-ის claims (მაგ. `aal` — Stage 23-ის MFA); `{}` — თუ ვერ წაიკითხა / override ტესტში
    claims: dict = field(default_factory=dict)
    token: str = field(default="", repr=False)  # raw access token (`confirm_with_auth_server`-ისთვის); repr-ში არ ხვდება
    # "local" | "network". `get_current_auth` ყოველთვის ცხადად აყენებს; default — მხოლოდ ტესტების override-ისთვის
    verified_by: str = "network"


def _extract_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <token> სავალდებულოა",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ცარიელი token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def _invalid_token() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_INVALID_TOKEN,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_auth(authorization: str | None = Header(default=None)) -> CurrentAuth:
    settings = get_settings()
    token = _extract_token(authorization)

    try:
        claims = jwt_verify.verify(token)
    except jwt_verify.InvalidToken:
        raise _invalid_token() from None

    client = create_client(settings.supabase_url, settings.supabase_publishable_key)

    if claims is not None:
        # ლოკალურად დადასტურებული; ამიერიდან ყველა postgrest მოთხოვნა ამ მომხმარებლის JWT-ით → RLS მოქმედებს
        client.postgrest.auth(token)
        return CurrentAuth(
            user_id=claims["sub"], email=claims.get("email"), client=client,
            claims=claims, token=token, verified_by="local",
        )

    try:
        user_resp = client.auth.get_user(token)
    except Exception:
        raise _invalid_token() from None

    user = getattr(user_resp, "user", None)
    if user is None or not getattr(user, "id", None):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token არ შეესაბამება მომხმარებელს",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ამიერიდან ყველა postgrest მოთხოვნა ამ მომხმარებლის JWT-ით → RLS მოქმედებს
    client.postgrest.auth(token)

    # Auth-მა ხელმოწერა უკვე დაადასტურა; claims მხოლოდ თუ იმავე მომხმარებელს ეკუთვნის
    claims = jwt_verify.unverified_claims(token)
    if claims.get("sub") != str(user.id):
        claims = {}

    return CurrentAuth(
        user_id=str(user.id), email=getattr(user, "email", None), client=client,
        claims=claims, token=token, verified_by="network",
    )


def confirm_with_auth_server(auth: CurrentAuth) -> None:
    """ლოკალურად შემოწმებული token-ის დადასტურება Supabase Auth-ით (sign-out / ban / წაშლა მაშინვე მოქმედებს).

    შეცდომა, user-ის არარსებობა ან სხვა `id` → 401.
    """
    try:
        user_resp = auth.client.auth.get_user(auth.token)
    except Exception:
        raise _invalid_token() from None
    user = getattr(user_resp, "user", None)
    if user is None or str(getattr(user, "id", "")) != auth.user_id:
        raise _invalid_token()
