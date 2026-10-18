from fastapi import APIRouter, HTTPException, Request, Response

from app.core import auth
from app.schemas.auth import LoginRequest, SessionView

router = APIRouter(prefix="/api/v1/auth", tags=["demo-auth"])


def view(request: Request, role: auth.Role | None) -> SessionView:
    settings = request.app.state.settings
    return SessionView(
        authenticated=role is not None, role=role, login_required=settings.require_login,
        admin_available=True,
        demo_edit_enabled=False)


@router.get("/me", response_model=SessionView)
def me(request: Request):
    return view(request, auth.current_role(request))


@router.post("/login", response_model=SessionView)
def login(body: LoginRequest, request: Request, response: Response):
    settings = request.app.state.settings
    auth.throttle(request)
    expected = (settings.demo_admin_passcode if body.role == "admin" else settings.demo_user_passcode).get_secret_value()
    # Blank defaults accept only blank input; configured passcodes still require an exact match.
    if not auth.check_passcode(body.passcode, expected):
        auth.record_failure(request)
        raise HTTPException(401, "invalid_credentials")
    auth.issue(request, response, body.role)
    return view(request, body.role)


@router.post("/logout", response_model=SessionView)
def logout(request: Request, response: Response):
    auth.clear(response)
    return view(request, None)
