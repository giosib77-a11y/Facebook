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

    # CORS — ნებადართული origin-ები (მძიმით გამოყოფილი). "*" = ყველა (მხოლოდ dev-ისთვის).
    # production-ში .env-ში: CORS_ORIGINS="https://shendomen.ge"
    cors_origins: str = "*"

    # Gemini (ბოტი — ნაბიჯი 4)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # ბოტის საუბრის მეხსიერება — ბოლო N შეტყობინება, ბოლო H საათში (0 = გამორთული)
    bot_memory_messages: int = 20
    bot_memory_hours: int = 24

    # Facebook Messenger (ნაბიჯი 5)
    fb_app_id: str = ""
    fb_app_secret: str = ""
    fb_verify_token: str = ""              # ჩვენი არჩეული token webhook-ის ვერიფიკაციისთვის
    fb_graph_version: str = "v21.0"
    fb_redirect_uri: str = ""              # backend callback (ngrok https + /facebook/connect/callback)
    # Facebook Login for Business — Login Configuration ID (business asset/page flow).
    # თუ დაყენებულია → config-based login (business-owned გვერდებისთვის); თუ არა → scope-based.
    fb_login_config_id: str = ""
    frontend_url: str = "http://localhost:5500"
    fb_token_encryption_key: str = ""      # Fernet key page token-ის დასაშიფრად

    # საჯარო base URL (პანელი/ფორმა აქედან იხსნება). ცარიელია → fb_redirect_uri-დან გამოითვლება.
    public_base_url: str = ""

    # ადმინ პანელის მფლობელი — მხოლოდ ეს email ხედავს /admin-ს (override .env-ში ADMIN_EMAIL-ით)
    admin_email: str = "giosib77@gmail.com"

    # გადახდის რეკვიზიტები (გამოწერისთვის) — შეავსე .env-ში PAYMENT_IBAN / PAYMENT_CONTACT-ით
    payment_iban: str = "[შენი ანგარიშის ნომერი — შეავსე PAYMENT_IBAN]"
    payment_contact: str = "[ქვითრის გამოსაგზავნი კონტაქტი — შეავსე PAYMENT_CONTACT]"

    model_config = SettingsConfigDict(
        env_file=(_ROOT_ENV, _BACKEND_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in ("production", "prod")

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS-ს სიად აქცევს. '*' → ['*']."""
        raw = (self.cors_origins or "").strip()
        if not raw or raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
