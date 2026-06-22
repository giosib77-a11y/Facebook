"""ავთენტიფიკაცია — Supabase access token-ის შემოწმება.

კლიენტი აგზავნის `Authorization: Bearer <supabase_access_token>`.
ჩვენ:
  1. ვამოწმებთ token-ს `auth.get_user()`-ით (Supabase Auth API).
  2. ვქმნით per-request Supabase კლიენტს anon key-ით და ვაყენებთ ამ token-ს
     PostgREST-ისთვის, რათა ყველა DB-მოთხოვნა შესრულდეს ამ მომხმარებლის სახელით
     — ანუ ნაბიჯ 1-ის RLS პოლისიები ავტომატურად მოქმედებენ.
"""
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from supabase import Client, create_client

from app.config import get_settings


@dataclass
class CurrentAuth:
    """ერთი მოთხოვნის ავტორიზებული კონტექსტი."""
    user_id: str
    email: str | None
    client: Client  # JWT-ით ავტორიზებული Supabase კლიენტი (RLS მოქმედებს)


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


def get_current_auth(authorization: str | None = Header(default=None)) -> CurrentAuth:
    settings = get_settings()
    token = _extract_token(authorization)

    client = create_client(settings.supabase_url, settings.supabase_anon_key)

    try:
        user_resp = client.auth.get_user(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token არასწორია ან ვადაგასულია",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = getattr(user_resp, "user", None)
    if user is None or not getattr(user, "id", None):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token არ შეესაბამება მომხმარებელს",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ამიერიდან ყველა postgrest მოთხოვნა ამ მომხმარებლის JWT-ით → RLS მოქმედებს
    client.postgrest.auth(token)

    return CurrentAuth(user_id=str(user.id), email=getattr(user, "email", None), client=client)
