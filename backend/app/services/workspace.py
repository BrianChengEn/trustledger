"""Structured sandbox snapshots shared by the personal and local Admin views."""
import hashlib
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, Request

from app.adapters.nessie import API_BASE, REMOTE_ID
from app.adapters.nessie_fixture import BASELINE_SHA256
from app.adapters.synthetic_dataset import identifier
from app.schemas.workspace import WorkspaceMovement, WorkspaceSnapshot
from app.schemas.transaction import Transaction
from app.core.transactions import AdapterHealth, SyntheticTransactionProvider


def context(request: Request):
    if hasattr(request.state, 'workspace_context'):
        return request.state.workspace_context
    state = request.app.state
    root = state.settings.demo_user_id
    if state.settings.transaction_provider == 'account-demo' and not request.path_params.get('customer_code'):
        rows = demo_account_rows(request)
        result = {'owner': rows[0].owner, 'customer_id': None, 'remote_id': None, 'scope': ''}
        request.state.workspace_context = result
        return result
    key = state.settings.nessie_api_key.get_secret_value()
    code = request.path_params.get('customer_code')
    connected = (bool(code) or state.settings.transaction_provider == 'nessie'
                 or request.path_params.get('source') == 'nessie')
    if connected and not key:
        raise HTTPException(503, 'nessie_not_configured')
    if not connected:
        key = ''
    scope = hashlib.sha256(key.encode()).hexdigest()
    remote = None
    if code:
        if not key:
            raise HTTPException(503, 'nessie_not_configured')
        if not re.fullmatch(r'customer_[0-9a-f]{32}', code):
            raise HTTPException(404, 'customer_not_found')
        remote = state.store.resolve_resource(root, scope, code)
        if remote is None:
            raise HTTPException(404, 'customer_not_found')
    elif key and state.settings.nessie_customer_id.get_secret_value():
        remote = state.settings.nessie_customer_id.get_secret_value()
        code = state.store.alias_resources(root, scope, 'customer', [remote])[remote]
    elif key:
        with state.store.connect() as db:
            row = db.execute("SELECT r.remote_id FROM seed_records r JOIN seed_runs s ON s.id=r.run_id "
                             "WHERE s.owner=? AND s.dataset_sha256=? AND s.api_base_url=? "
                             "AND s.credential_fingerprint=? AND r.kind='customer' "
                             "AND r.local_id=? AND r.state='confirmed'",
                             (root, BASELINE_SHA256, API_BASE, scope, identifier('c', 1))).fetchone()
        if row is None:
            raise HTTPException(409, 'workspace_not_linked')
        remote = row['remote_id']
        code = state.store.alias_resources(root, scope, 'customer', [remote])[remote]
    if remote is not None and not REMOTE_ID.fullmatch(remote):
        raise HTTPException(409, 'workspace_not_linked')
    result = {'owner': f'{root}:nessie:{scope}:{code}' if code else root,
              'customer_id': code, 'remote_id': remote, 'scope': scope}
    request.state.workspace_context = result
    return result


def owner(request):
    return context(request)['owner']


class WorkspaceTransactionProvider(SyntheticTransactionProvider):
    def __init__(self, request):
        view = snapshot(request)
        rows = []
        for movement in view.transactions:
            row = Transaction(**{name: getattr(movement, name) for name in Transaction.model_fields})
            row._date_only = movement.date_only
            row._settlement_status = movement.settlement_status
            rows.append(row)
        super().__init__(rows, owner(request))
        self.data_mode = view.data_mode

    def health(self):
        return AdapterHealth(status='degraded' if self.data_mode == 'degraded' else 'ok',
                             data_mode=self.data_mode)


def select_customer(customer_code: str, request: Request):
    return context(request)


def token(prefix, customer_owner, remote):
    return prefix + hashlib.sha256((customer_owner + ':' + remote).encode()).hexdigest()[:32]


def account_codes(store, root, scope, rows):
    aliases = store.alias_resources(root, scope, 'account', [row['_id'] for row in rows])
    members = [row for row in rows if isinstance(row.get('customer_id'), str)
               and REMOTE_ID.fullmatch(row['customer_id'])]
    customers = store.alias_resources(root, scope, 'customer', [row['customer_id'] for row in members])
    codes = {row['_id']: token('acct_', f"{root}:nessie:{scope}:{customers[row['customer_id']]}", row['_id'])
             for row in members}
    store.bind_account_codes(root, scope, codes)
    return {**aliases, **codes}


def cents(value, *, negative=False):
    if type(value) not in (int, float):
        raise ValueError('Invalid money')
    result = Decimal(str(value)) * 100
    if not result.is_finite() or result != result.to_integral_value() or abs(result) > 9007199254740991:
        raise ValueError('Invalid cents')
    if result < 0 and not negative:
        raise ValueError('Negative amount')
    return int(result)


def collection(capture):
    body = capture['response_body']
    if (capture['body_format'] != 'json' or not isinstance(body, list) or len(body) > 1000
            or not all(isinstance(row, dict) for row in body)):
        raise ValueError('Invalid collection')
    if any('_id' in row and 'id' in row and row['_id'] != row['id'] for row in body):
        raise ValueError('Conflicting collection identifiers')
    body = [{**row, '_id': row.get('_id', row.get('id'))} for row in body]
    ids = [row['_id'] for row in body]
    if (not all(isinstance(value, str) and REMOTE_ID.fullmatch(value) for value in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('Invalid collection identifiers')
    return body


def movements(rows, customer_owner, account, kind):
    result = []
    for row in rows:
        value = (row.get('purchase_date') or row.get('transaction_date')) if kind == 'purchases' else row.get('transaction_date')
        if not isinstance(value, str):
            raise ValueError('Missing date')
        date_only = bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value))
        occurred = (datetime.combine(date.fromisoformat(value), datetime.min.time(), timezone.utc)
                    if date_only else datetime.fromisoformat(value))
        direction = 'credit' if kind == 'deposits' else 'debit'
        if kind == 'transfers':
            if 'payer_id' not in row and 'payee_id' not in row:
                direction = 'unknown'
            else:
                payer, payee = row.get('payer_id') == account, row.get('payee_id') == account
                if payer == payee:
                    raise ValueError('Invalid transfer membership')
                direction = 'debit' if payer else 'credit'
        movement = WorkspaceMovement(
            id=token('txn_', customer_owner, kind + ':' + account + ':' + row['_id']),
            account_token=token('acct_', customer_owner, account),
            occurred_at=occurred, amount=cents(row.get('amount')) / 100, currency='USD',
            direction=direction, merchant_display=kind[:-1].capitalize(), merchant_category='other',
            source='nessie', is_subscription=False, kind=kind[:-1],
            settlement_status=row.get('status'), date_only=date_only)
        result.append((movement.id, movement.account_token, movement.kind,
                       movement.occurred_at.isoformat(), int(date_only), cents(movement.amount),
                       direction, movement.settlement_status))
    return result


def snapshot(request):
    state, ctx = request.app.state, context(request)
    if state.settings.transaction_provider == 'account-demo' and ctx['customer_id'] is None:
        rows = [WorkspaceMovement(
            id=row.id, account_token=row.account_token, amount=row.amount_minor / 100,
            currency=row.currency, kind=row.kind, direction=row.direction, source='nessie',
            occurred_at=(row.occurred_at if row.occurred_at is not None else
                         datetime.combine(row.occurred_date, datetime.min.time(), timezone.utc)),
            date_only=row.occurred_date is not None, settlement_status=row.settlement_status,
            merchant_display=row.merchant_display if row.merchant_display is not None else row.kind.capitalize(),
            merchant_category=row.merchant_category if row.merchant_category is not None else 'other',
            is_subscription=row.is_subscription if row.is_subscription is not None else False)
            for row in demo_account_rows(request)]
        return WorkspaceSnapshot(customer_id=None, data_mode='synthetic', accounts=[],
                                 transactions=sorted(rows, key=lambda row: row.occurred_at, reverse=True), sync=[])
    if ctx['customer_id'] is None:
        rows = [WorkspaceMovement(**row.model_dump(), settlement_status='completed',
                                  date_only=False) for row in state.store.list_transactions(ctx['owner'])]
        return WorkspaceSnapshot(customer_id=None, data_mode='synthetic', accounts=[], transactions=rows, sync=[])
    accounts, stored, sync = state.store.workspace_rows(ctx['owner'])
    rows = []
    for record in stored:
        movement = WorkspaceMovement(
            id=record['id'], account_token=record['account_token'], occurred_at=record['occurred_at'],
            amount=record['amount_cents'] / 100, currency='USD', direction=record['direction'],
            merchant_display=record['kind'].capitalize(), merchant_category='other', source='nessie',
            is_subscription=False, kind=record['kind'], settlement_status=record['settlement_status'],
            date_only=bool(record['date_only']))
        movement._date_only = movement.date_only
        rows.append(movement)
    return WorkspaceSnapshot(
        customer_id=ctx['customer_id'], data_mode='degraded' if not sync or any(row['error'] for row in sync) else 'nessie-live',
        accounts=[{'account_token': row['account_token'], 'type': row['type'],
                   'balance': row['balance_cents'] / 100, 'rewards': row['rewards']} for row in accounts],
        # shortcut: match the existing 100-record analysis window; add pagination for larger histories.
        transactions=sorted(rows, key=lambda row: row.occurred_at, reverse=True)[:100],
        sync=[{key: value for key, value in row.items() if key != 'owner'} for row in sync])


def demo_account_rows(request):
    # The source registry owns identity; never copy these rows into the 18-record baseline.
    from app.services.data_sources import account_store
    if hasattr(request.state, 'demo_account_rows'):
        return request.state.demo_account_rows
    code = request.app.state.settings.demo_account_token
    store = account_store(request, 'nessie')
    result = store.account_page(code, limit=100) if store else None
    if result is None:
        raise HTTPException(503, 'account_dataset_unavailable')
    rows, total = result
    if (total != 100 or len(rows) != 100 or len({row.id for row in rows}) != 100
            or len({row.owner for row in rows}) != 1
            or any(row.account_token != code or row.currency != 'USD' or row.kind == 'unknown'
                   or row.settlement_status is None
                   or (row.occurred_at is None and row.occurred_date is None) for row in rows)):
        raise HTTPException(503, 'account_dataset_unavailable')
    request.state.demo_account_rows = rows
    return rows


def refresh(request):
    state, ctx = request.app.state, context(request)
    request.state.nessie_failed = False
    if ctx['customer_id'] is None:
        return snapshot(request)

    def acquire(path, account_token, kind, project):
        requested_at = datetime.now(timezone.utc).isoformat()
        capture = state.nessie.request('GET', path)
        error = capture['transport_error']['type'] if capture['transport_error'] else (
            'upstream' if capture['http_status'] != 200 else None)
        rows = None
        if error is None:
            try:
                rows = project(collection(capture))
            except (ValueError, TypeError, InvalidOperation):
                error = 'schema'
        if error is not None:
            request.state.nessie_failed = True
        state.store.save_workspace_collection(ctx['owner'], account_token, kind, rows,
                                               requested_at, capture['http_status'], error)
        return rows

    account_ids = []

    def accounts(rows):
        projected = []
        for row in rows:
            if (row.get('customer_id') != ctx['remote_id']
                    or row.get('type') not in {'Checking', 'Savings', 'Credit Card'}
                    or type(row.get('rewards')) is not int or not 0 <= row['rewards'] <= 9007199254740991):
                raise ValueError('Invalid account membership or shape')
            projected.append((token('acct_', ctx['owner'], row['_id']), row['type'],
                              cents(row.get('balance'), negative=True), row['rewards']))
            account_ids.append(row['_id'])
        account_codes(state.store, state.settings.demo_user_id, ctx['scope'], rows)
        return projected

    rows = acquire(f"/customers/{ctx['remote_id']}/accounts", '', 'accounts', accounts)
    if rows is not None:
        for account in account_ids:
            for kind in ('purchases', 'transfers', 'deposits', 'withdrawals'):
                acquire(f'/accounts/{account}/{kind}', token('acct_', ctx['owner'], account), kind,
                        lambda body: movements(body, ctx['owner'], account, kind))
    from app.services.data_sources import synchronize_nessie
    synchronize_nessie(request)
    return snapshot(request)


def require_nessie(request: Request):
    connected = bool(request.path_params.get('customer_code')) or request.app.state.settings.transaction_provider == 'nessie'
    request.state.transaction_provenance = {
        'provider': 'nessie-live' if connected else 'synthetic-test',
        'upstream_status': 'unavailable', 'fallback_used': 'false',
    }
    if not connected:
        return None
    view = refresh(request)
    if request.state.nessie_failed or view.data_mode == 'degraded':
        raise HTTPException(502, 'nessie_unavailable')
    request.state.transaction_provenance['upstream_status'] = 'live'
    return view
