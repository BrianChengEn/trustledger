import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")
    app_env: str = "development"
    transaction_provider: Literal["synthetic", "nessie", "account-demo"] = "synthetic"
    demo_account_token: str | None = Field(default=None, pattern=r'^acct_[0-9a-f]{32}$')
    fraud_provider: Literal["rules-only", "mock-jev", "backboard-jev"] = "rules-only"
    # A single local demo identity; this is not an authentication mechanism.
    demo_user_id: str = "demo-user-001"
    frontend_origin: str = "http://localhost:5173"
    allow_memory_write: bool = False
    database_path: Path = BACKEND_DIR / "data" / "trustledger-demo.db"
    source_database_dir: Path | None = None
    nessie_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    jev_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    backboard_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    # Server-side explanation only. A missing key keeps the rules explanation and does not call Gemini.
    gemini_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_ms: int = Field(default=8000, ge=1000, le=20000)
    # Demo sign-in (not production authentication). With REQUIRE_LOGIN=true every data route needs a session.
    # An empty USER passcode makes user sign-in open; an empty ADMIN passcode disables admin sign-in entirely.
    require_login: bool = False
    demo_user_passcode: SecretStr = Field(default=SecretStr(""), repr=False)
    demo_admin_passcode: SecretStr = Field(default=SecretStr(""), repr=False)
    # Signs session cookies. Empty means a random secret per server start (sessions end when the server restarts).
    session_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    session_ttl_minutes: int = Field(default=480, ge=5, le=1440)
    # Admin editing of the synthetic demo data. Off unless explicitly enabled.
    allow_demo_edit: bool = False

    @model_validator(mode='after')
    def selected_demo_account(self):
        if self.transaction_provider == 'account-demo' and self.demo_account_token is None:
            raise ValueError('account-demo requires DEMO_ACCOUNT_TOKEN')
        return self

    @field_validator("frontend_origin")
    @classmethod
    def exact_frontend_origin(cls, value: str) -> str:
        try:
            origin = urlsplit(value)
            valid = (
                origin.scheme in {"http", "https"} and origin.hostname
                and origin.port != 0 and not origin.username and not origin.password
                and not origin.path and not origin.query and not origin.fragment
                and "*" not in value and not any(c.isspace() for c in value)
                and "?" not in value and "#" not in value
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("frontend_origin must be an exact HTTP(S) origin")
        return value

    @field_validator("gemini_model")
    @classmethod
    def gemini_model_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", value):
            raise ValueError("gemini_model must be a model id")
        return value
