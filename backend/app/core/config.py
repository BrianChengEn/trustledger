from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")
    app_env: str = "development"
    transaction_provider: Literal["synthetic", "nessie"] = "synthetic"
    fraud_provider: Literal["rules-only", "mock-jev", "backboard-jev"] = "rules-only"
    # A single local demo identity; this is not an authentication mechanism.
    demo_user_id: str = "demo-user-001"
    frontend_origin: str = "http://localhost:5173"
    allow_memory_write: bool = False
    database_path: Path = BACKEND_DIR / "data" / "trustledger-demo.db"
    nessie_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    jev_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    backboard_api_key: SecretStr = Field(default=SecretStr(""), repr=False)

    # Local demo only: blank passcodes allow blank sign-in for either role.
    require_login: bool = False
    demo_user_passcode: SecretStr = Field(default=SecretStr(""), repr=False)
    demo_admin_passcode: SecretStr = Field(default=SecretStr(""), repr=False)
    session_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    session_ttl_minutes: int = Field(default=480, ge=5, le=1440)

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
