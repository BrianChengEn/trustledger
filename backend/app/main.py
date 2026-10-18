from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException

from app.adapters.nessie import NessieClient
from app.adapters.synthetic import load_transactions
from app.api.admin_demo import router as demo_router
from app.api.admin_nessie import router as admin_router
from app.api.data_sources import router as source_router
from app.api.auth import router as auth_router
from app.api.routes import customer_router, router
from app.api.workspace import router as workspace_router
from app.core.config import Settings
from app.core.demo_edit import DemoEditError
from app.core.http import RequestGuardMiddleware, ResponseSecurityMiddleware, error_response
from app.core.store import Store
from app.core.dataset_store import DatasetStore
from app.services.ai.gemini_explanation import ExplanationCache
from app.core.transactions import ProviderError, TransactionNotFound


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="TrustLedger synthetic development API", version="0.3.1")
    app.state.settings = settings or Settings()
    app.state.store = Store(app.state.settings.database_path)
    source_dir = app.state.settings.source_database_dir or app.state.settings.database_path.parent / 'sources'
    app.state.source_stores = {name: DatasetStore(source_dir / f'{name}.db', name)
                               for name in ('nessie', 'banksim')}
    load_transactions(app.state.store, app.state.settings.demo_user_id)
    app.state.nessie = NessieClient(app.state.settings.nessie_api_key.get_secret_value())
    app.state.explanation_cache = ExplanationCache()
    origins = list({app.state.settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"})
    # Last added is outermost: response headers -> request guard -> CORS -> routes.
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type"])
    app.add_middleware(RequestGuardMiddleware, origins=origins)
    app.add_middleware(ResponseSecurityMiddleware)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        # Exception details may contain upstream URLs, secrets or raw data.
        code = {404: "not_found", 405: "method_not_allowed", 409: "confirmation_conflict",
                502: "memory_delete_failed"}.get(
            exc.status_code, "request_failed")
        admin_codes = {404: {"history_not_found", "resource_not_found"}, 503: {"nessie_not_configured"}}
        workspace_codes = {404: {'customer_not_found'}, 409: {'workspace_not_linked'},
                           502: {'customers_unavailable', 'nessie_unavailable'}, 503: {'nessie_not_configured'}}
        if isinstance(exc.detail, str) and exc.detail in workspace_codes.get(exc.status_code, set()):
            code = exc.detail
        if (request.url.path.startswith("/api/v1/admin/nessie") and isinstance(exc.detail, str)
                and exc.detail in admin_codes.get(exc.status_code, set())):
            code = exc.detail
        # Sign-in and demo-edit codes are fixed, safe strings chosen by this server.
        gate_codes = {401: {"auth_required", "invalid_credentials"}, 403: {"admin_only", "admin_not_configured",
                      "demo_edit_disabled"}, 409: {"not_synthetic_mode"}, 429: {"too_many_attempts"}}
        if isinstance(exc.detail, str) and exc.detail in gate_codes.get(exc.status_code, set()):
            code = exc.detail
        return error_response(request.scope, exc.status_code, code, "Request could not be completed.")

    @app.exception_handler(DemoEditError)
    async def demo_edit_error(request: Request, exc: DemoEditError):
        return error_response(request.scope, exc.status, exc.code, "Request could not be completed.")

    @app.exception_handler(ProviderError)
    async def provider_error(request: Request, exc: ProviderError):
        if isinstance(exc, TransactionNotFound):
            return error_response(request.scope, 404, "not_found", "Request could not be completed.")
        # Preserve the existing generic failure envelope; never expose adapter details.
        return error_response(request.scope, 500, "internal_error",
                              "Request failed; use the request ID for diagnosis.")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic errors can include raw input; never return them here.
        return error_response(request.scope, 422, "invalid_request", "Request does not match the API contract.")

    app.include_router(router)
    app.include_router(customer_router)
    app.include_router(workspace_router)
    app.include_router(admin_router)
    app.include_router(source_router)
    app.include_router(auth_router)
    app.include_router(demo_router)
    return app


app = create_app()
