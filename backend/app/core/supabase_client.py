"""Supabase კლიენტის ფაბრიკა.

ორი კლიენტი:
  - anon კლიენტი — publishable key + მომხმარებლის JWT-ით, RLS მოქმედებს (frontend-ის სახელით).
  - service კლიენტი — secret key-ით (legacy: service_role), RLS-ს გვერდს უვლის. გამოიყენება
    ბოტისთვის (Messenger webhook), რომელსაც სჭირდება მარაგის წაკითხვა
    მომხმარებლის სესიის გარეშე. არასდროს გადააგზავნო frontend-ში!

HTTP კავშირი: ორივე კლიენტი პროცესში ერთია (`lru_cache`) და მას ერთდროულად ყველა თრედი
იყენებს (API-ის threadpool, webhook worker, ბოტის limiter). supabase-py საკუთარ httpx-ს
`http2=True`-ით ქმნის — HTTP/2-ზე ყველა თრედის მოთხოვნა **ერთ** TLS socket-ზე მიდის, httpcore კი
წაკითხვასა და ჩაწერას სხვადასხვა lock-ით იცავს → ერთდროული recv/send ერთ SSL ობიექტზე →
`httpx.ReadError: [Errno 11] Resource temporarily unavailable` (ლაივი, `GET /admin/growth`).
ამიტომ supabase-py-ს ვაძლევთ საკუთარ httpx-ს: HTTP/1.1 (pool თითო მოთხოვნას საკუთარ კავშირს
აძლევს — თრედებს შორის უსაფრთხოა) და ცხადი timeout (default 120 წმ-ის ნაცვლად).
URL და header-ები (apikey / Authorization) supabase-py ყოველ მოთხოვნას თავად ატანს, ამიტომ
ერთი httpx client postgrest-ს, storage-სა და auth-ს შორის საერთოდ უსაფრთხოა.
"""
from functools import lru_cache

import httpx
from supabase import Client, ClientOptions, create_client

from app.config import get_settings

# ერთ მოთხოვნაზე: კავშირი 5 წმ, წაკითხვა / ჩაწერა 30 წმ, თავისუფალი კავშირის ლოდინი pool-ში 10 წმ.
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=5.0, pool=10.0)
# API-ის threadpool (40) + ბოტის limiter (BOT_MAX_CONCURRENCY, 8) + worker — 64 საკმარისია
HTTP_LIMITS = httpx.Limits(max_connections=64, max_keepalive_connections=20)


@lru_cache
def get_http_client() -> httpx.Client:
    """პროცესის ერთი httpx client Supabase-ისთვის — HTTP/1.1, timeout-ით, თრედებს შორის უსაფრთხო."""
    return httpx.Client(http2=False, timeout=HTTP_TIMEOUT, limits=HTTP_LIMITS, follow_redirects=True)


def _options() -> ClientOptions:
    # ახალი ობიექტი თითო კლიენტზე: supabase-py `options.headers`-ს თავის key-ს უწერს
    return ClientOptions(httpx_client=get_http_client())


@lru_cache
def get_service_client() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_secret_key, options=_options())


@lru_cache
def get_anon_client() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_publishable_key, options=_options())
