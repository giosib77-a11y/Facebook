"""Supabase კლიენტის ფაბრიკა.

ორი კლიენტი:
  - anon კლიენტი — მომხმარებლის JWT-ით, RLS მოქმედებს (frontend-ის სახელით).
  - service კლიენტი — service_role key-ით, RLS-ს გვერდს უვლის. გამოიყენება
    ბოტისთვის (Messenger webhook), რომელსაც სჭირდება მარაგის წაკითხვა
    მომხმარებლის სესიის გარეშე. არასდროს გადააგზავნო frontend-ში!
"""
from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def get_service_client() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


@lru_cache
def get_anon_client() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key)
