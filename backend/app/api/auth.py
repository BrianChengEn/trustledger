from fastapi import APIRouter, HTTPException, Request, Response

from app.core import auth
from app.schemas.auth import LoginRequest, SessionView

router = APIRouter(prefix="/api/v1/auth", tags=["demo-auth"])


def view(request: Request, role: auth.Role | None) -> SessionView:
    settings = request.app.state.settings
    return SessionView(
        authenticated=role is not None, role=role, login_required=settings.require_login,
        admin_available=bool(settings.demo_admin_passcode.get_secret_value()),
        demo_edit_enabled=settings.allow_demo_edit)


@router.get("/me", response_model=SessionView)
def me(request: Request):
    return view(request, auth.current_role(request))


@router.post("/login", response_model=SessionView)
def login(body: LoginRequest, request: Request, response: Response):
    settings = request.app.state.settings
    auth.throttle(request)
    expected = (settings.demo_admin_passcode if body.role == "admin" else settings.demo_user_passcode).get_secret_value()
    if body.role == "admin" and not expected:
        # No admin passcode configured: admin sign-in does not exist, so there is nothing to guess.
        raise HTTPException(403, "admin_not_configured")
    # An empty user passcode means the demo user sign-in is open.
    if expected and not auth.check_passcode(body.passcode, expected):
        auth.record_failure(request)
        raise HTTPException(401, "invalid_credentials")
    auth.issue(request, response, body.role)
    return view(request, body.role)


@router.post("/logout", response_model=SessionView)
def logout(request: Request, response: Response):
    auth.clear(response)
    return view(request, None)
