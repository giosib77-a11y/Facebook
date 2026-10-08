"""T19: Settings must not leak secrets in repr/str, and tests must not read a local .env."""
from app.config import Settings, get_settings

SECRET_ENVS = (
    "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "ORIGIN_SECRET", "GEMINI_API_KEY",
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
    assert get_settings().supabase_service_role_key == ""
