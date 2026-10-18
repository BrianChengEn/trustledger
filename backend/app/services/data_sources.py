"""Canonical source pages; research storage never enters the product inference path."""
from datetime import datetime, timezone

from app.adapters.dataset_import import nessie_record
from app.schemas.dataset import SourcePage, SourceTransaction
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


def source_page(request, source, limit=25, offset=0):
    ctx = context(request) if source == 'nessie' else None
    rows, total, mode, last = request.app.state.source_stores[source].source_page(
        ctx['owner'] if ctx else None, limit=limit, offset=offset)
    return SourcePage(source=source, items=[SourceTransaction.from_record(row) for row in rows],
                      total=total, next_offset=offset + limit if offset + limit < total else None,
                      data_mode=mode, last_synced_at=last,
                      customer_code=ctx['customer_id'] if ctx else None)
