"""აპლიკაციის პარამეტრები — იკითხება .env-დან (pydantic-settings)."""
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# root .env და backend/.env — ორივეს ვცდილობთ წაკითხვას
_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = ""
    # ახალი API key-ები (sb_publishable_... / sb_secret_...). ძველი legacy სახელები
    # (SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY) fallback-ად მუშაობს; ახალი სახელი უპირატესია.
    supabase_publishable_key: str = Field(
        "", repr=False,
        validation_alias=AliasChoices("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY"),
    )
    supabase_secret_key: str = Field(
        "", repr=False,
        validation_alias=AliasChoices("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )

    # App
    # fail-closed: APP_ENV-ის გარეშე production. dev-ში .env-ში APP_ENV=development (A-4)
    app_env: str = "production"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # CORS — ნებადართული origin-ები (მძიმით გამოყოფილი). "*" = ყველა (მხოლოდ dev-ისთვის).
    # production-ში .env-ში: CORS_ORIGINS="https://shendomen.ge"
    cors_origins: str = "*"

    # კლიენტის IP = X-Forwarded-For-ის მარჯვნიდან N-ური ჩანაწერი (1 = ბოლო). Render ამატებს
    # ჩანაწერებს მარჯვნივ; მარცხენა ჩანაწერები კლიენტის კონტროლშია. CF-Connecting-IP იგნორირდება.
    client_ip_trusted_hops: int = 1
    # დროებითი diagnostic: true → ლოგში XFF/peer/არჩეული IP (მაქს. 10 წმ-ში ერთხელ).
    client_ip_debug: bool = False

    # `app` logger-ის დონე (stdout-ზე): DEBUG / INFO / WARNING / ERROR. არავალიდური → INFO.
    log_level: str = "INFO"

    # Origin lock (FA-03): proxy-ს (მაგ. Cloudflare Transform Rule) ამ header-ს საიდუმლოთი ამატებს.
    # production-ში, თუ დაყენებულია, origin-ზე პირდაპირი მოთხოვნა (header-ის გარეშე) → 403.
    # ახლა არ გამოიყენება (Cloudflare არ არის); T13 — Backlog.
    origin_secret: str = Field("", repr=False)
    origin_secret_header: str = "x-origin-secret"

    # Gemini (ბოტი — ნაბიჯი 4)
    gemini_api_key: str = Field("", repr=False)
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = 20.0  # ერთი Gemini მცდელობის timeout (S11-3)

    # ბოტის საუბრის მეხსიერება — ბოლო N შეტყობინება, ბოლო H საათში (0 = გამორთული)
    bot_memory_messages: int = 20
    bot_memory_hours: int = 24

    # Facebook Messenger (ნაბიჯი 5)
    fb_app_id: str = ""
    fb_app_secret: str = Field("", repr=False)
    fb_verify_token: str = Field("", repr=False)              # ჩვენი არჩეული token webhook-ის ვერიფიკაციისთვის
    fb_graph_version: str = "v21.0"
    fb_redirect_uri: str = ""              # backend callback (ngrok https + /facebook/connect/callback)
    # Facebook Login for Business — Login Configuration ID (business asset/page flow).
    # თუ დაყენებულია → config-based login (business-owned გვერდებისთვის); თუ არა → scope-based.
    fb_login_config_id: str = ""
    frontend_url: str = "http://localhost:5500"
    fb_token_encryption_key: str = Field("", repr=False)      # Fernet key page token-ის დასაშიფრად

    # საჯარო base URL (პანელი/ფორმა აქედან იხსნება). ცარიელია → fb_redirect_uri-დან გამოითვლება.
    public_base_url: str = ""

    # ადმინ პანელის მფლობელები — Supabase user UUID-ები, მძიმით (.env-ში ADMIN_USER_IDS).
    # ცარიელი = ადმინი არავინაა (fail closed). email სტაბილური იდენტობა არ არის.
    admin_user_ids: str = ""

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

    def missing_required_secrets(self) -> list[str]:
        """Production-ში სავალდებულო პარამეტრებიდან ცარიელ/არავალიდურთა ENV სახელები.

        ⚠️ მხოლოდ სახელები — მნიშვნელობები არასდროს ბრუნდება/ილოგება.
        """
        required = {
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_PUBLISHABLE_KEY": self.supabase_publishable_key,
            "SUPABASE_SECRET_KEY": self.supabase_secret_key,
            "GEMINI_API_KEY": self.gemini_api_key,
            "FB_APP_SECRET": self.fb_app_secret,
            "FB_VERIFY_TOKEN": self.fb_verify_token,
            "FB_TOKEN_ENCRYPTION_KEY": self.fb_token_encryption_key,
        }
        missing = [name for name, value in required.items() if not (value or "").strip()]
        if "FB_TOKEN_ENCRYPTION_KEY" not in missing:
            try:
                Fernet(self.fb_token_encryption_key.encode())  # როგორც crypto._fernet()
            except Exception:
                missing.append("FB_TOKEN_ENCRYPTION_KEY (invalid format)")
        return missing

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS-ს სიად აქცევს. '*' → ['*']."""
        raw = (self.cors_origins or "").strip()
        if not raw or raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def admin_user_id_set(self) -> set[str]:
        """ADMIN_USER_IDS → stripped, lower-cased, non-empty UUID-ების set."""
        return {u.strip().lower() for u in (self.admin_user_ids or "").split(",") if u.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
