from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters.synthetic import load_transactions
from app.api.routes import router
from app.core.config import Settings
from app.core.store import Store


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="TrustLedger synthetic development API", version="0.1.0")
    app.state.settings = settings or Settings()
    app.state.transactions = load_transactions()
    app.state.store = Store(app.state.settings.database_path)
    origins = list({app.state.settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"})
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])

    def error(request, status, code, message):
        return JSONResponse(status_code=status, content={"error": {
            "code": code, "message": message,
            "request_id": getattr(request.state, "request_id", "unavailable"),
        }})

    @app.middleware("http")
    async def protect_requests(request: Request, call_next):
        request.state.request_id = uuid4().hex
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
    return app


app = create_app()
