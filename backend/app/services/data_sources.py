"""Canonical source pages; research storage never enters the product inference path."""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.account_dataset import AccountDataset

from app.adapters.dataset_import import nessie_record
from app.schemas.dataset import SourceAccountPage, SourcePage, SourceTransaction
from app.services.workspace import context


def synchronize_nessie(request):
    state, ctx = request.app.state, context(request)
    if ctx['customer_id'] is None:
        return
    captured_at = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    _, rows, collections = state.store.workspace_rows(ctx['owner'])
    state.source_stores['nessie'].sync_nessie_snapshot(
        ctx['owner'], (nessie_record(row) for row in rows),
        [{key: value for key, value in row.items() if key != 'owner'} for row in collections], captured_at)


def account_store(request, source):
    state = request.app.state
    if state.settings.app_env != 'test':
        return None
    if source not in state.account_stores:
        directory = state.source_stores[source].filename.parent / 'account-demo'
        if not (directory / 'manifest.json').is_file():
            return None
        if not all((directory / f'{name}.db').is_file() for name in ('nessie', 'banksim')):
            raise HTTPException(503, 'account_dataset_unavailable')
        state.account_stores[source] = AccountDataset(directory / f'{source}.db', source)
    return state.account_stores[source]


def account_options(request, source, limit, offset, q):
    store = account_store(request, source)
    rows, total = store.accounts(limit=limit, offset=offset, q=q) if store else ([], 0)
    return SourceAccountPage(items=rows, total=total,
                             next_offset=offset + limit if offset + limit < total else None)


def source_page(request, source, limit=25, offset=0, account_token=None):
    if account_token is not None:
        store = account_store(request, source)
        result = store.account_page(account_token, limit=limit, offset=offset) if store else None
        if result is None:
            raise HTTPException(404, 'resource_not_found')
        rows, total = result
        return SourcePage(source=source, items=[SourceTransaction.from_record(row) for row in rows],
                          total=total, next_offset=offset + limit if offset + limit < total else None,
                          data_mode='synthetic-derived')
    ctx = context(request) if source == 'nessie' else None
    rows, total, mode, last = request.app.state.source_stores[source].source_page(
        ctx['owner'] if ctx else None, limit=limit, offset=offset)
    return SourcePage(source=source, items=[SourceTransaction.from_record(row) for row in rows],
                      total=total, next_offset=offset + limit if offset + limit < total else None,
                      data_mode=mode, last_synced_at=last,
                      customer_code=ctx['customer_id'] if ctx else None)
