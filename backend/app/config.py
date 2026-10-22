from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRETS = {"", "change-me"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_base_url: str = "http://localhost:3000"
    session_secret: str = "change-me"
    session_days: int = 7
    org_name: str = "My organization"

    database_url: str = "postgresql+psycopg://rino:rino@localhost:5432/rino"
    redis_url: str = "redis://localhost:6379/0"

    bootstrap_admin_github_login: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""

    dev_login_enabled: bool = False

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def github_configured(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)

    @property
    def dev_login_allowed(self) -> bool:
        return self.dev_login_enabled and not self.is_production

    @property
    def oauth_callback_url(self) -> str:
        return f"{self.app_base_url.rstrip('/')}/api/auth/github/callback"

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if self.is_production:
            if self.session_secret in INSECURE_SECRETS or len(self.session_secret) < 32:
                raise ValueError("SESSION_SECRET must be a random string of 32+ characters in production")
            if self.dev_login_enabled:
                raise ValueError("DEV_LOGIN_ENABLED must be false in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
