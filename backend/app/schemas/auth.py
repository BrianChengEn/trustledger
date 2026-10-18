from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(AuthModel):
    role: Literal["user", "admin"]
    # Blank defaults for either role; configured passcodes require an exact match. Never echoed back.
    passcode: str = Field(default="", max_length=64)


class SessionView(AuthModel):
    authenticated: bool
    role: Literal["user", "admin"] | None = None
    # True when the server rejects data requests that have no session.
    login_required: bool
    # Local demo admin supports blank sign-in by default.
    admin_available: bool
    # True when admins may edit the synthetic demo data (ALLOW_DEMO_EDIT).
    demo_edit_enabled: bool
