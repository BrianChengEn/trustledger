from typing import Literal

from fastapi import APIRouter, Depends, Query, Request

from app.core.auth import require_admin_when_enforced
from app.schemas.dataset import SourceAccountPage, SourcePage
from app.services.data_sources import account_options, source_page
from app.services.workspace import refresh

router = APIRouter(prefix='/api/v1/data-sources', dependencies=[Depends(require_admin_when_enforced)])


@router.get('/{source}/transactions', response_model=SourcePage)
def transactions(source: Literal['nessie', 'banksim'], request: Request,
                 limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
                 account_token: str | None = Query(None, pattern=r'^acct_[0-9a-f]{32}$')):
    return source_page(request, source, limit, offset, account_token)


@router.get('/{source}/accounts', response_model=SourceAccountPage)
def accounts(source: Literal['nessie', 'banksim'], request: Request,
             limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
             q: str = Query('', max_length=80)):
    return account_options(request, source, limit, offset, q)


@router.post('/nessie/refresh', response_model=SourcePage)
def refresh_nessie(request: Request):
    # Literal routes have no source path param; explicit source context never mutates settings.
    request.path_params['source'] = 'nessie'
    refresh(request)
    return source_page(request, 'nessie')
