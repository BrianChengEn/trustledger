import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from app.schemas.admin_nessie import (
    DeleteOutcome, DeleteRequest, Execution, HistoryItem, HistoryPage, QueryRequest, ResourceOption,
)
from app.services.nessie_console import execute_query, require_console_nessie
from app.services.workspace import account_codes, collection, context

router = APIRouter(prefix="/api/v1/admin/nessie", tags=["local-admin"])
HistoryId = Annotated[int, Path(gt=0)]


@router.get('/customers', response_model=list[ResourceOption])
def customers(request: Request):
    result = query(QueryRequest(query='customers.list'), request)
    if result['http_status'] != 200 or result['body_format'] != 'json':
        raise HTTPException(502, 'customers_unavailable')
    rows = [{'resource_id': row['resource_id'], 'kind': 'customer'} for row in result['response_body']]
    if request.app.state.settings.transaction_provider == 'nessie':
        try:
            primary = context(request)['customer_id']
        except HTTPException as exc:
            if exc.detail != 'workspace_not_linked':
                raise
        else:
            if not any(row['resource_id'] == primary for row in rows):
                raise HTTPException(409, 'workspace_not_linked')
            rows.sort(key=lambda row: row['resource_id'] != primary)
    return rows


@router.post("/query", response_model=Execution)
def query(body: QueryRequest, request: Request):
    state = request.app.state
    key = state.settings.nessie_api_key
    if not key or not key.get_secret_value():
        raise HTTPException(503, "nessie_not_configured")
    scope = hashlib.sha256(key.get_secret_value().encode()).hexdigest()
    return execute_query(body, state.nessie, state.store, state.settings.demo_user_id, scope)


@router.get("/history", response_model=HistoryPage, dependencies=[Depends(require_console_nessie)])
def history(request: Request, before_id: Annotated[int | None, Query(gt=0)] = None):
    state = request.app.state
    return state.store.list_history(state.settings.demo_user_id, before_id)


@router.get("/resources", response_model=list[ResourceOption], dependencies=[Depends(require_console_nessie)])
def resources(request: Request):
    state = request.app.state
    key = state.settings.nessie_api_key.get_secret_value()
    scope = hashlib.sha256(key.encode()).hexdigest()
    capture = state.nessie.query('accounts.list', None)
    if capture['http_status'] != 200:
        raise HTTPException(502, 'nessie_unavailable')
    try:
        account_codes(state.store, state.settings.demo_user_id, scope, collection(capture))
    except (TypeError, ValueError):
        raise HTTPException(502, 'nessie_unavailable') from None
    return state.store.list_resources(state.settings.demo_user_id, scope)


@router.get("/history/{history_id}", response_model=HistoryItem, dependencies=[Depends(require_console_nessie)])
def detail(history_id: HistoryId, request: Request):
    state = request.app.state
    record = state.store.get_history(state.settings.demo_user_id, history_id)
    if record is None:
        raise HTTPException(404, "history_not_found")
    return record


@router.delete("/history/{history_id}", response_model=DeleteOutcome, dependencies=[Depends(require_console_nessie)])
def delete(history_id: HistoryId, body: DeleteRequest, request: Request):
    state = request.app.state
    count = state.store.delete_history(state.settings.demo_user_id, history_id)
    if not count:
        raise HTTPException(404, "history_not_found")
    return {"deleted": count}


@router.delete("/history", response_model=DeleteOutcome, dependencies=[Depends(require_console_nessie)])
def clear(body: DeleteRequest, request: Request):
    state = request.app.state
    return {"deleted": state.store.delete_history(state.settings.demo_user_id)}
