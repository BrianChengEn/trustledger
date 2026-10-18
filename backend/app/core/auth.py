"""Demo sign-in: a signed session cookie carrying a role. This is a demo gate, not production authentication.

Sessions are HMAC-signed with a server secret and expire. Passcodes live only in backend settings and are compared in
constant time. Nothing here is ever logged. Real accounts, password hashing and rate limiting at the edge are out of scope.
"""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Literal

from fastapi import HTTPException, Request, Response

COOKIE = "tl_session"
Role = Literal["user", "admin"]
# Paths that must stay reachable without a session (liveness and the sign-in endpoints themselves).
OPEN_PATHS = {"/api/v1/health"}
_LOCK = threading.Lock()
_FAILURES: dict[str, list[float]] = {}
MAX_FAILURES, WINDOW_SECONDS = 8, 60


def _secret(request: Request) -> bytes:
    app = request.app
    configured = app.state.settings.session_secret.get_secret_value().strip()
    if configured:
        return configured.encode()
    if not getattr(app.state, "generated_session_secret", None):
        app.state.generated_session_secret = secrets.token_bytes(32)
    return app.state.generated_session_secret


def _sign(secret: bytes, body: bytes) -> str:
    return base64.urlsafe_b64encode(hmac.new(secret, body, hashlib.sha256).digest()).decode().rstrip("=")


def issue(request: Request, response: Response, role: Role) -> None:
    settings = request.app.state.settings
    ttl = settings.session_ttl_minutes * 60
    body = base64.urlsafe_b64encode(json.dumps({"role": role, "exp": int(time.time()) + ttl}, separators=(",", ":")).encode())
    token = body.decode().rstrip("=") + "." + _sign(_secret(request), body)
    response.set_cookie(COOKIE, token, max_age=ttl, httponly=True, samesite="strict", path="/")


def clear(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict")


def current_role(request: Request) -> Role | None:
    raw = request.cookies.get(COOKIE)
    if not raw or raw.count(".") != 1:
        return None
    encoded, signature = raw.split(".")
    body = (encoded + "=" * (-len(encoded) % 4)).encode()
    if not hmac.compare_digest(signature, _sign(_secret(request), body)):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("role") not in ("user", "admin"):
        return None
    if not isinstance(payload.get("exp"), int) or payload["exp"] < time.time():
        return None
    return payload["role"]


def check_passcode(supplied: str, expected: str) -> bool:
    return hmac.compare_digest(supplied.encode(), expected.encode())


def throttle(request: Request) -> None:
    """Allow a handful of failed sign-ins per minute per client address."""
    client = request.client.host if request.client else "unknown"
    now = time.time()
    with _LOCK:
        recent = [t for t in _FAILURES.get(client, []) if now - t < WINDOW_SECONDS]
        _FAILURES[client] = recent
        if len(recent) >= MAX_FAILURES:
            raise HTTPException(429, "too_many_attempts")


def record_failure(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    with _LOCK:
        _FAILURES.setdefault(client, []).append(time.time())


def reset_failures() -> None:
    with _LOCK:
        _FAILURES.clear()


def require_session(request: Request) -> None:
    """Router-level gate for data routes. Inactive unless REQUIRE_LOGIN is on, so existing local tooling keeps working."""
    if not request.app.state.settings.require_login or request.scope.get("path") in OPEN_PATHS:
        return
    if current_role(request) is None:
        raise HTTPException(401, "auth_required")


def require_admin_when_enforced(request: Request) -> None:
    """The Nessie admin console: admin only when sign-in is enforced."""
    if not request.app.state.settings.require_login:
        return
    role = current_role(request)
    if role is None:
        raise HTTPException(401, "auth_required")
    if role != "admin":
        raise HTTPException(403, "admin_only")


def require_admin(request: Request) -> None:
    """Demo data editing: always needs an admin session, whatever REQUIRE_LOGIN says."""
    role = current_role(request)
    if role is None:
        raise HTTPException(401, "auth_required")
    if role != "admin":
        raise HTTPException(403, "admin_only")
