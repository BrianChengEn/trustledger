from fastapi import APIRouter, Depends, Request

from app.schemas.workspace import WorkspaceSnapshot
from app.services.workspace import require_nessie, select_customer, snapshot

router = APIRouter()


@router.post('/api/v1/workspace/refresh', response_model=WorkspaceSnapshot)
@router.post('/api/v1/admin/nessie/customers/{customer_code}/workspace/refresh',
             response_model=WorkspaceSnapshot, dependencies=[Depends(select_customer)])
def refresh_workspace(request: Request):
    view = require_nessie(request)
    return view if view is not None else snapshot(request)
