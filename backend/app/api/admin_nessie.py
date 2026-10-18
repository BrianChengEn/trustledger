import hashlib
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request

from app.schemas.admin_nessie import (
    DeleteOutcome, DeleteRequest, Execution, HistoryItem, HistoryPage, QueryRequest, ResourceOption,
)
from app.services.nessie_console import execute_query

router = APIRouter(prefix="/api/v1/admin/nessie", tags=["local-admin"])
HistoryId = Annotated[int, Path(gt=0)]


@router.post("/query", response_model=Execution)
def query(body: QueryRequest, request: Request):
    state = request.app.state
    key = state.settings.nessie_api_key
    if not key or not key.get_secret_value():
        raise HTTPException(503, "nessie_not_configured")
    scope = hashlib.sha256(key.get_secret_value().encode()).hexdigest()
    return execute_query(body, state.nessie, state.store, state.settings.demo_user_id, scope)


@router.get("/history", response_model=HistoryPage)
def history(request: Request, before_id: Annotated[int | None, Query(gt=0)] = None):
    state = request.app.state
    return state.store.list_history(state.settings.demo_user_id, before_id)


@router.get("/resources", response_model=list[ResourceOption])
def resources(request: Request):
    state = request.app.state
    key = state.settings.nessie_api_key.get_secret_value()
    scope = hashlib.sha256(key.encode()).hexdigest()
    return state.store.list_resources(state.settings.demo_user_id, scope)


@router.get("/history/{history_id}", response_model=HistoryItem)
def detail(history_id: HistoryId, request: Request):
    state = request.app.state
    record = state.store.get_history(state.settings.demo_user_id, history_id)
    if record is None:
        raise HTTPException(404, "history_not_found")
    return record


@router.delete("/history/{history_id}", response_model=DeleteOutcome)
def delete(history_id: HistoryId, body: DeleteRequest, request: Request):
    state = request.app.state
    count = state.store.delete_history(state.settings.demo_user_id, history_id)
    if not count:
        raise HTTPException(404, "history_not_found")
    return {"deleted": count}


@router.delete("/history", response_model=DeleteOutcome)
def clear(body: DeleteRequest, request: Request):
    state = request.app.state
    return {"deleted": state.store.delete_history(state.settings.demo_user_id)}
