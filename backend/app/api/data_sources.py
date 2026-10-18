from typing import Literal

from fastapi import APIRouter, Query, Request

from app.schemas.dataset import SourcePage
from app.services.data_sources import source_page
from app.services.workspace import refresh

router = APIRouter(prefix='/api/v1/data-sources')


@router.get('/{source}/transactions', response_model=SourcePage)
def transactions(source: Literal['nessie', 'banksim'], request: Request,
                 limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
    return source_page(request, source, limit, offset)


@router.post('/nessie/refresh', response_model=SourcePage)
def refresh_nessie(request: Request):
    # Literal routes have no source path param; explicit source context never mutates settings.
    request.path_params['source'] = 'nessie'
    refresh(request)
    return source_page(request, 'nessie')
