from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters.nessie import NessieClient
from app.adapters.synthetic import load_transactions
from app.api.admin_nessie import router as admin_router
from app.api.routes import router
from app.core.config import Settings
from app.core.store import Store


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="TrustLedger synthetic development API", version="0.1.0")
    app.state.settings = settings or Settings()
    app.state.store = Store(app.state.settings.database_path)
    load_transactions(app.state.store, app.state.settings.demo_user_id)
    app.state.nessie = NessieClient(app.state.settings.nessie_api_key.get_secret_value())
    origins = list({app.state.settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"})
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    admin_origins = {origin for origin in origins if urlsplit(origin).hostname in local_hosts}
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])

    def error(request, status, code, message):
        request_id = getattr(request.state, "request_id", "unavailable")
        return JSONResponse(status_code=status, headers={"X-Request-ID": request_id,
                            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                            content={"error": {
            "code": code, "message": message,
            "request_id": request_id,
        }})

    @app.middleware("http")
    async def protect_requests(request: Request, call_next):
        request.state.request_id = uuid4().hex
        if request.url.path.startswith("/api/v1/admin/nessie"):
            host = request.url.hostname
            origin = request.headers.get("origin")
            if host not in local_hosts or (origin and origin not in admin_origins):
                return error(request, 403, "local_access_only", "Local access is required.")
            if request.method in {"POST", "DELETE"} and (
                origin not in admin_origins or
                request.headers.get("content-type", "").split(";")[0].strip().lower()
                    != "application/json"
            ):
                return error(request, 403, "local_json_required", "Local JSON access is required.")
        # Local-only starter: no session cookies or production identity is claimed.
        # Reject unexpected browser origins (CORS alone would still allow side effects).
        if request.method in {"POST", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and origin not in origins:
                return error(request, 403, "origin_denied", "Request origin is not allowed.")
        size = request.headers.get("content-length")
        if size and (not size.isdigit() or int(size) > 16384):
            return error(request, 413, "request_too_large", "Request body exceeds the local API limit.")
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error(request, exc.status_code, str(exc.detail), "Request could not be completed.")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic errors can include raw input; never return them here.
        return error(request, 422, "invalid_request", "Request does not match the API contract.")

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        return error(request, 500, "internal_error", "Request failed; use the request ID for diagnosis.")

    app.include_router(router)
    app.include_router(admin_router)
    return app


app = create_app()
