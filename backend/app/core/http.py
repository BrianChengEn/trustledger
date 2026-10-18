"""Local API request limits and response handling; never log request data."""
import logging
from uuid import uuid4
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders, URL
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.schemas.api import ErrorDetail, ErrorEnvelope

BODY_LIMIT = 16384
logger = logging.getLogger(__name__)


def error_response(scope: Scope, status: int, code: str, message: str) -> JSONResponse:
    envelope = ErrorEnvelope(error=ErrorDetail(
        code=code, message=message,
        request_id=scope.get("state", {}).get("request_id", "unavailable"),
    ))
    return JSONResponse(status_code=status, content=envelope.model_dump(mode="json"))


class ResponseSecurityMiddleware:
    """Wrap CORS too, so preflights and all early responses get the same headers."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def secure_send(message: Message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
                # Explicit allowlist: no URL, path, query, headers, body or exception text.
                logger.info("api_response", extra={
                    "request_id": request_id, "status_code": message["status"],
                })
            await send(message)

        await self.app(scope, receive, secure_send)


class RequestGuardMiddleware:
    """Bounded pre-read prevents route side effects before the full body is checked.

    Retain at most BODY_LIMIT bytes, then replay once through ASGI receive. Response
    streaming is untouched. ASGI servers own transport framing and chunk decoding.
    """

    def __init__(self, app: ASGIApp, origins: list[str]):
        self.app = app
        self.origins = origins
        self.local_hosts = {"localhost", "127.0.0.1", "::1"}
        self.admin_origins = {origin for origin in origins if urlsplit(origin).hostname in self.local_hosts}

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def tracked_send(message: Message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.handle(scope, receive, tracked_send)
        except Exception:
            if started:
                # A response cannot be replaced after headers have reached the client.
                raise RuntimeError("Response failed after headers were sent.") from None
            await self.respond(scope, receive, send, 500, "internal_error",
                               "Request failed; use the request ID for diagnosis.")

    async def handle(self, scope: Scope, receive: Receive, send: Send):
        headers = Headers(scope=scope)
        if scope.get("path", "").startswith(("/api/v1/admin/nessie", "/api/v1/admin/demo", "/api/v1/data-sources")):
            origin = headers.get("origin")
            if URL(scope=scope).hostname not in self.local_hosts or (origin and origin not in self.admin_origins):
                return await self.respond(scope, receive, send, 403, "local_access_only", "Local access is required.")
            if scope["method"] in {"POST", "PATCH", "DELETE"} and (
                origin not in self.admin_origins or
                headers.get("content-type", "").split(";")[0].strip().lower() != "application/json"
            ):
                return await self.respond(scope, receive, send, 403, "local_json_required", "Local JSON access is required.")
        if scope["method"] in {"POST", "PATCH", "DELETE"}:
            origin = headers.get("origin")
            if origin and origin not in self.origins:
                return await self.respond(scope, receive, send, 403, "origin_denied",
                                          "Request origin is not allowed.")
        sizes = headers.getlist("content-length")
        # Bound parsing too: int() must never see an arbitrarily long header value.
        invalid_size = len(sizes) > 1 or any(
            not size or not size.isascii() or not size.isdecimal()
            or len(size) > 5 or int(size) > BODY_LIMIT for size in sizes
        )
        if invalid_size:
            return await self.too_large(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > BODY_LIMIT:
                return await self.too_large(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        # Never trust a smaller declared size; reject inconsistent framing safely.
        if sizes and len(body) != int(sizes[0]):
            return await self.respond(scope, receive, send, 400, "invalid_request",
                                      "Request does not match the API contract.")
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def too_large(self, scope: Scope, receive: Receive, send: Send):
        await self.respond(scope, receive, send, 413, "request_too_large",
                           "Request body exceeds the local API limit.")

    async def respond(self, scope, receive, send, status, code, message):
        response = error_response(scope, status, code, message)
        # Guard errors occur before CORSMiddleware; preserve its exact-origin,
        # no-credentials policy so the frontend can read these errors as well.
        origin = Headers(scope=scope).get("origin")
        if origin in self.origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        await response(scope, receive, send)
