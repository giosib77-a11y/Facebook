"""T19: Settings must not leak secrets in repr/str, and tests must not read a local .env."""
from app.config import Settings, get_settings

SECRET_ENVS = (
    "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY", "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY", "ORIGIN_SECRET", "GEMINI_API_KEY",
    "FB_APP_SECRET", "FB_VERIFY_TOKEN", "FB_TOKEN_ENCRYPTION_KEY",
)


def test_repr_and_str_hide_secrets(monkeypatch):
    sentinels = {}
    for i, name in enumerate(SECRET_ENVS):
        sentinels[name] = f"SENTINEL-SECRET-{i}-{name}"
        monkeypatch.setenv(name, sentinels[name])
    s = Settings()
    # the sentinels really were loaded, so absence from repr is meaningful
    assert s.gemini_api_key == sentinels["GEMINI_API_KEY"]
    assert s.fb_token_encryption_key == sentinels["FB_TOKEN_ENCRYPTION_KEY"]
    out = repr(s) + str(s)
    assert "SENTINEL" not in out


def test_test_config_ignores_dotenv_in_cwd(tmp_path, monkeypatch):
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "GEMINI_API_KEY=FROM-DOTENV-FILE\nFB_APP_SECRET=FROM-DOTENV-FILE\n"
        "APP_ENV=production\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    # drop conftest's blank env pins so only the dotenv mechanism could supply a value
    for name in ("GEMINI_API_KEY", "FB_APP_SECRET", "APP_ENV"):
        monkeypatch.delenv(name)
    # positive control: the file is a valid dotenv and *would* be read if enabled
    assert Settings(_env_file=fake_env).gemini_api_key == "FROM-DOTENV-FILE"
    # plain Settings() under the test config must not read it
    assert Settings.model_config["env_file"] is None
    s = Settings()
    assert s.gemini_api_key == ""
    assert s.fb_app_secret == ""
    assert s.app_env == "production"  # class default, not "staging" from the file
    assert get_settings().supabase_secret_key == ""


def test_new_key_names_are_read(monkeypatch):
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_NEW")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_NEW")
    s = Settings()
    assert s.supabase_publishable_key == "sb_publishable_NEW"
    assert s.supabase_secret_key == "sb_secret_NEW"


def test_old_key_names_work_as_fallback(monkeypatch):
    # conftest pins the new names to "" (an *empty* new var still shadows the old one) -> unset
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY")
    monkeypatch.delenv("SUPABASE_SECRET_KEY")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "legacy-anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "legacy-service")
    s = Settings()
    assert s.supabase_publishable_key == "legacy-anon"
    assert s.supabase_secret_key == "legacy-service"


def test_new_key_names_win_over_old(monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "legacy-anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "legacy-service")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_NEW")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_NEW")
    s = Settings()
    assert s.supabase_publishable_key == "sb_publishable_NEW"
    assert s.supabase_secret_key == "sb_secret_NEW"


def test_env_names_are_case_insensitive(monkeypatch):
    monkeypatch.setenv("supabase_secret_key", "lower-case-secret")
    assert Settings().supabase_secret_key == "lower-case-secret"


def test_repr_hides_both_new_and_old_key_names(monkeypatch):
    for name in ("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY",
                 "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.setenv(name, f"SENTINEL-{name}")
    s = Settings()
    out = repr(s) + str(s)
    assert "SENTINEL" not in out
    assert "supabase_secret_key" not in out and "supabase_publishable_key" not in out


def test_production_default_unchanged_without_keys():
    s = Settings(_env_file=None)
    assert s.supabase_publishable_key == "" and s.supabase_secret_key == ""
    # fail-closed default is still production when APP_ENV is absent
    assert Settings.model_fields["app_env"].default == "production"
