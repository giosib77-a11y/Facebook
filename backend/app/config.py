"""აპლიკაციის პარამეტრები — იკითხება .env-დან (pydantic-settings)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# root .env და backend/.env — ორივეს ვცდილობთ წაკითხვას
_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # Gemini (ბოტი — ნაბიჯი 4)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Facebook Messenger (ნაბიჯი 5)
    fb_app_id: str = ""
    fb_app_secret: str = ""
    fb_verify_token: str = ""              # ჩვენი არჩეული token webhook-ის ვერიფიკაციისთვის
    fb_graph_version: str = "v21.0"
    fb_redirect_uri: str = ""              # backend callback (ngrok https + /facebook/connect/callback)
    frontend_url: str = "http://localhost:5500"
    fb_token_encryption_key: str = ""      # Fernet key page token-ის დასაშიფრად

    # საჯარო base URL (პანელი/ფორმა აქედან იხ სნება). ცარიელია → fb_redirect_uri-დან გამოითვლება.
    public_base_url: str = ""

    model_config = SettingsConfigDict(
        env_file=(_ROOT_ENV, _BACKEND_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
