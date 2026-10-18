from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")
    app_env: str = "development"
    # A single local demo identity; this is not an authentication mechanism.
    demo_user_id: str = "demo-user-001"
    frontend_origin: str = "http://localhost:5173"
    allow_memory_write: bool = True
    database_path: Path = BACKEND_DIR / "data" / "trustledger-demo.db"
    nessie_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    jev_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    backboard_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
