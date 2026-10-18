import hashlib

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.nessie import API_BASE, NessieClient
from app.adapters.nessie_fixture import BASELINE_SHA256
from app.adapters.synthetic_dataset import identifier
from app.core.config import Settings
from app.main import create_app

PREFIX = '/api/v1/admin/nessie'
CUSTOMERS = ['c' * 24, 'd' * 24]
ACCOUNTS = ['a' * 24, 'b' * 24]


@pytest.fixture
def workspace(tmp_path):
    app = create_app(Settings(_env_file=None, database_path=tmp_path / 'workspace.db',
                             nessie_api_key='workspace-key', backboard_api_key='', transaction_provider='nessie',
                             allow_memory_write=True))
    behavior = {'fail': set(), 'calls': [], 'overrides': {}}

    def upstream(request):
        path = request.url.path
        behavior['calls'].append((request.method, path))
        if any(path.endswith(suffix) for suffix in behavior['fail']):
            return httpx.Response(404, text='Not Found')
        for suffix, body in behavior['overrides'].items():
            if path.endswith(suffix):
                return httpx.Response(200, json=body)
        if path == '/customers':
            body = [{'_id': customer, 'first_name': 'PRIVATE NAME'} for customer in CUSTOMERS]
        elif path == '/accounts':
            body = [{'_id': account, 'customer_id': customer, 'type': 'Checking',
                     'balance': 1234.56, 'rewards': 2} for customer, account in zip(CUSTOMERS, ACCOUNTS)]
        elif path.endswith('/accounts'):
            customer = path.split('/')[2]
            body = [{'_id': ACCOUNTS[CUSTOMERS.index(customer)], 'customer_id': customer,
                     'type': 'Checking', 'balance': 1234.56, 'rewards': 2,
                     'nickname': 'PRIVATE NICKNAME'}]
        elif path.endswith(('/purchases', '/transfers')):
            body = []
        else:
            kind = 'withdrawal' if path.endswith('/withdrawals') else 'deposit'
            body = [{'_id': ('e' if kind == 'withdrawal' else 'f') * 24,
                     'amount': 849 if kind == 'withdrawal' else 100,
                     'transaction_date': '2026-10-17', 'status': 'completed',
                     'medium': 'balance', 'description': 'PRIVATE DESCRIPTION'}]
        return httpx.Response(200, json=body)

    app.state.nessie = NessieClient('workspace-key', transport=httpx.MockTransport(upstream))
    with TestClient(app, base_url='http://127.0.0.1',
                    headers={'origin': 'http://localhost:5173'}) as client:
        options = client.post(PREFIX + '/query', json={'query': 'customers.list'}).json()['response_body']
        yield client, [row['resource_id'] for row in options], behavior


def test_failed_collection_stops_refresh_and_preserves_safe_cache(workspace):
    client, customers, behavior = workspace
    prefix = PREFIX + '/customers/' + customers[0]
    response = client.post(prefix + '/workspace/refresh', json={})
    assert response.status_code == 200
    data = response.json()
    assert data['customer_id'] == customers[0]
    assert data['data_mode'] == 'nessie-live'
    assert data['accounts'][0]['balance'] == 1234.56
    assert {row['kind'] for row in data['transactions']} == {'deposit', 'withdrawal'}
    assert all(row['date_only'] and row['source'] == 'nessie' for row in data['transactions'])
    transfer = next(row for row in data['sync'] if row['kind'] == 'transfers')
    assert transfer['http_status'] == 200 and transfer['synced_at'] is not None
    assert all(raw not in response.text for raw in [*CUSTOMERS, *ACCOUNTS, 'PRIVATE'])
    behavior['fail'].update({'/withdrawals', '/transfers'})
    assert client.post(prefix + '/workspace/refresh', json={}).status_code == 502
    owner = 'demo-user-001:nessie:' + hashlib.sha256(b'workspace-key').hexdigest() + ':' + customers[0]
    _, stored, sync = client.app.state.store.workspace_rows(owner)
    assert len(stored) == 2
    withdrawal = next(row for row in sync if row['kind'] == 'withdrawals')
    assert withdrawal['http_status'] == 404 and withdrawal['synced_at'] is not None
    assert 'PRIVATE' not in client.app.state.store.filename.read_bytes().decode(errors='ignore')
    assert all(method == 'GET' for method, _ in behavior['calls'])


def test_customer_review_memory_and_privacy_are_isolated(workspace):
    client, customers, _ = workspace
    first, second = [PREFIX + '/customers/' + code for code in customers]
    first_data = client.post(first + '/workspace/refresh', json={}).json()
    client.post(second + '/workspace/refresh', json={})
    tx = next(row for row in first_data['transactions'] if row['kind'] == 'withdrawal')
    privacy = client.get(first + '/privacy/preview/' + tx['id'])
    assert privacy.status_code == 200
    assert privacy.json()['safe_payload']['local_day_part'] == 'unknown'
    alert = client.get(first + '/alerts').json()[0]
    assert alert['status'] == 'open'
    confirmed = client.post(first + '/alerts/' + alert['alert_id'] + '/confirmations',
                            json={'decision': 'normal', 'consent_to_memory': True})
    assert confirmed.status_code == 200 and confirmed.json()['memory_status'] == 'written'
    memory = client.get(first + '/memories').json()[0]
    assert client.get(second + '/memories').json() == []
    assert client.get(second + '/alerts').json()[0]['status'] == 'open'
    assert client.get(second + '/privacy/preview/' + tx['id']).status_code == 404
    assert client.delete(second + '/memories/' + memory['memory_id'],
                         headers={'content-type': 'application/json'}).status_code == 404
    assert client.post(second + '/alerts/' + alert['alert_id'] + '/confirmations',
                       json={'decision': 'normal', 'consent_to_memory': True}).status_code == 404
    assert client.get(first + '/alerts').json()[0]['status'] == 'normal'


def test_fixed_mapping_reuses_admin_state_and_survives_restart(workspace):
    client, customers, behavior = workspace
    assert client.post('/api/v1/workspace/refresh', json={}).status_code == 409
    store = client.app.state.store
    with store.connect() as db:
        run = db.execute('INSERT INTO seed_runs(owner,dataset_sha256,api_base_url,credential_fingerprint,'
                         "state,created_at,updated_at) VALUES(?,?,?,?,'complete','now','now')",
                         ('demo-user-001', BASELINE_SHA256, API_BASE,
                          hashlib.sha256(b'workspace-key').hexdigest())).lastrowid
        db.execute("INSERT INTO seed_records(run_id,kind,local_id,remote_id,request_fingerprint,state,updated_at) "
                   "VALUES(?,'customer',?,?,'test','confirmed','now')", (run, identifier('c', 1), CUSTOMERS[0]))
    data = client.post('/api/v1/workspace/refresh', json={}).json()
    assert data['customer_id'] == customers[0]
    alert = client.get('/api/v1/alerts').json()[0]
    client.post('/api/v1/alerts/' + alert['alert_id'] + '/confirmations',
                json={'decision': 'review', 'consent_to_memory': False}).raise_for_status()
    assert client.get(PREFIX + '/customers/' + customers[0] + '/alerts').json()[0]['status'] == 'review'
    assert len(client.get(PREFIX + '/customers').json()) == 2
    before = list(behavior['calls'])
    with TestClient(create_app(client.app.state.settings)) as restarted:
        restarted.app.state.nessie = NessieClient('workspace-key', transport=httpx.MockTransport(
            lambda request: httpx.Response(503)))
        assert restarted.get('/api/v1/transactions').status_code == 502
        owner = 'demo-user-001:nessie:' + hashlib.sha256(b'workspace-key').hexdigest() + ':' + customers[0]
        assert len(store.workspace_rows(owner)[1]) == 2
        assert len(store.list_transactions('demo-user-001')) == 18
    assert behavior['calls'] == before


@pytest.mark.parametrize('change', [{'amount': 0.001}, {'amount': True},
                                   {'transaction_date': '2026-02-30'}, {'status': 'PRIVATE'}])
def test_invalid_collection_preserves_cache_without_persisting_raw_fields(workspace, change):
    client, customers, behavior = workspace
    prefix = PREFIX + '/customers/' + customers[0]
    first = client.post(prefix + '/workspace/refresh', json={}).json()
    row = {'_id': 'e' * 24, 'amount': 12, 'transaction_date': '2026-10-17',
           'status': 'completed', **change}
    behavior['overrides']['/withdrawals'] = [row]
    assert client.post(prefix + '/workspace/refresh', json={}).status_code == 502
    owner = 'demo-user-001:nessie:' + hashlib.sha256(b'workspace-key').hexdigest() + ':' + customers[0]
    _, stored, sync = client.app.state.store.workspace_rows(owner)
    assert {row['id'] for row in stored} == {row['id'] for row in first['transactions']}
    status = next(row for row in sync if row['kind'] == 'withdrawals')
    assert status['error'] == 'schema' and status['synced_at'] is not None


def test_unowned_or_raw_customer_input_stops_before_upstream(workspace):
    client, _, behavior = workspace
    before = list(behavior['calls'])
    for code in [CUSTOMERS[0], 'customer_' + '0' * 32, 'account_' + '0' * 32]:
        assert client.post(PREFIX + '/customers/' + code + '/workspace/refresh', json={}).status_code == 404
        assert client.get(PREFIX + '/customers/' + code + '/memories').status_code == 404
    assert behavior['calls'] == before


def test_transfer_legs_and_noncompleted_movements_are_not_completed_charge_alerts(workspace):
    client, customers, behavior = workspace
    behavior['fail'].clear()
    behavior['overrides']['/transfers'] = [{'_id': '1' * 24, 'payer_id': ACCOUNTS[0],
        'payee_id': ACCOUNTS[1], 'amount': 12.34, 'transaction_date': '2026-10-17', 'status': 'completed'}]
    behavior['overrides']['/withdrawals'] = [{'_id': '2' * 24, 'amount': 900,
        'transaction_date': '2026-10-17', 'status': 'cancelled'}]
    for code, direction in zip(customers, ['debit', 'credit']):
        prefix = PREFIX + '/customers/' + code
        data = client.post(prefix + '/workspace/refresh', json={}).json()
        transfer = next(row for row in data['transactions'] if row['kind'] == 'transfer')
        assert transfer['direction'] == direction and transfer['amount'] == 12.34
        assert client.get(prefix + '/alerts').json() == []


def test_nessie_generic_merchant_labels_do_not_imply_duplicate_purchases(workspace):
    client, customers, behavior = workspace
    behavior['overrides']['/withdrawals'] = []
    behavior['overrides']['/purchases'] = [
        {'_id': str(index) * 24, 'merchant_id': str(index + 2) * 24, 'amount': 20,
         'purchase_date': f'2026-10-17T{hour}:00:00+00:00', 'status': 'completed'}
        for index, hour in [(1, '10'), (2, '11')]
    ]
    prefix = PREFIX + '/customers/' + customers[0]
    data = client.post(prefix + '/workspace/refresh', json={}).json()
    assert len([row for row in data['transactions'] if row['kind'] == 'purchase']) == 2
    assert client.get(prefix + '/alerts').json() == []


def test_existing_human_decision_remains_inspectable_after_the_rule_no_longer_matches(workspace):
    client, customers, behavior = workspace
    prefix = PREFIX + '/customers/' + customers[0]
    client.post(prefix + '/workspace/refresh', json={})
    alert = client.get(prefix + '/alerts').json()[0]
    client.post(prefix + '/alerts/' + alert['alert_id'] + '/confirmations',
                json={'decision': 'review', 'consent_to_memory': False}).raise_for_status()
    behavior['overrides']['/withdrawals'] = [{'_id': 'e' * 24, 'amount': 10,
        'transaction_date': '2026-10-17', 'status': 'completed'}]
    client.post(prefix + '/workspace/refresh', json={})
    alerts = client.get(prefix + '/alerts').json()
    assert len(alerts) == 1 and alerts[0]['status'] == 'review' and alerts[0]['alert_type'] == 'none'


def test_cache_rejects_removed_account_writes_and_older_responses(workspace):
    client, _, _ = workspace
    store = client.app.state.store
    owner = 'isolated-cache-owner'
    account = ('acct_test', 'Checking', 10000, 0)
    old = '2026-10-17T10:00:00+00:00'
    new = '2026-10-17T11:00:00+00:00'
    movement = ('txn_test', 'acct_test', 'purchase', old, 0, 100, 'debit', 'completed')
    store.save_workspace_collection(owner, '', 'accounts', [account], old, 200, None)
    store.save_workspace_collection(owner, '', 'accounts', [], new, 200, None)
    store.save_workspace_collection(owner, 'acct_test', 'purchases', [movement], old, 200, None)
    store.save_workspace_collection(owner, '', 'accounts', [account], old, 200, None)
    accounts, movements, _ = store.workspace_rows(owner)
    assert accounts == [] and movements == []
    latest = '2026-10-17T12:00:00+00:00'
    store.save_workspace_collection(owner, '', 'accounts', [account], latest, 200, None)
    store.save_workspace_collection(owner, 'acct_test', 'purchases', [movement], latest, 200, None)
    store.save_workspace_collection(owner, 'acct_test', 'purchases', [], old, 500, 'upstream')
    _, movements, sync = store.workspace_rows(owner)
    assert len(movements) == 1
    assert next(row for row in sync if row['kind'] == 'purchases')['error'] is None


def test_provider_transfer_id_without_parties_keeps_unknown_direction(workspace):
    client, customers, behavior = workspace
    behavior['fail'].clear()
    behavior['overrides']['/transfers'] = [{'id': '1' * 24, 'amount': 900,
        'transaction_date': '2026-10-17', 'status': 'completed'}]
    prefix = PREFIX + '/customers/' + customers[0]
    response = client.post(prefix + '/workspace/refresh', json={})
    assert response.status_code == 200
    transfers = [row for row in response.json()['transactions'] if row['kind'] == 'transfer']
    assert len(transfers) == 1
    assert transfers[0]['direction'] == 'unknown'
    assert transfers[0]['id'] not in {a['transaction_id'] for a in client.get(prefix + '/alerts').json()}
    assert client.get(prefix + '/privacy/preview/' + transfers[0]['id']).status_code == 200


def test_admin_first_customer_matches_overview_despite_upstream_order(workspace):
    client, customers, behavior = workspace
    store = client.app.state.store
    with store.connect() as db:
        run = db.execute('INSERT INTO seed_runs(owner,dataset_sha256,api_base_url,credential_fingerprint,'
                         "state,created_at,updated_at) VALUES(?,?,?,?,'complete','now','now')",
                         ('demo-user-001', BASELINE_SHA256, API_BASE,
                          hashlib.sha256(b'workspace-key').hexdigest())).lastrowid
        db.execute("INSERT INTO seed_records(run_id,kind,local_id,remote_id,request_fingerprint,state,updated_at) "
                   "VALUES(?,'customer',?,?,'test','confirmed','now')", (run, identifier('c', 1), CUSTOMERS[0]))
    behavior['overrides']['/customers'] = [{'_id': row} for row in reversed(CUSTOMERS)]
    options = client.get(PREFIX + '/customers').json()
    assert options[0]['resource_id'] == customers[0]
    overview = client.post('/api/v1/workspace/refresh', json={}).json()
    admin = client.post(PREFIX + '/customers/' + options[0]['resource_id'] + '/workspace/refresh', json={}).json()
    assert overview['customer_id'] == options[0]['resource_id']
    assert overview['transactions'] == admin['transactions']


def test_workspace_account_code_is_queryable_in_admin_with_legacy_alias_compatibility(workspace):
    client, customers, behavior = workspace
    scope = hashlib.sha256(b'workspace-key').hexdigest()
    store = client.app.state.store
    legacy = store.alias_resources('demo-user-001', scope, 'account', [ACCOUNTS[0]])[ACCOUNTS[0]]
    view = client.post(PREFIX + '/customers/' + customers[0] + '/workspace/refresh', json={}).json()
    code = view['accounts'][0]['account_token']
    result = client.post(PREFIX + '/query', json={'query': 'accounts.by_customer',
                                                 'resource_id': customers[0]})
    assert result.json()['response_body'][0]['resource_id'] == code
    options = client.get(PREFIX + '/resources').json()
    assert {'resource_id': code, 'kind': 'account'} in options
    assert {'resource_id': legacy, 'kind': 'account'} not in options
    for selected in [code, legacy]:
        response = client.post(PREFIX + '/query', json={'query': 'transfers.by_account',
                                                        'resource_id': selected})
        assert response.status_code == 200 and response.json()['http_status'] == 200
        assert behavior['calls'][-1] == ('GET', '/accounts/' + ACCOUNTS[0] + '/transfers')
    from app.core.store import Store
    restarted = Store(store.filename)
    assert restarted.resolve_resource('demo-user-001', scope, code) == ACCOUNTS[0]
    assert restarted.resolve_resource('demo-user-001', scope, legacy) == ACCOUNTS[0]
    assert restarted.resolve_resource('other', scope, code) is None
    assert restarted.resolve_resource('demo-user-001', 'other-key', code) is None
    assert all(raw not in result.text for raw in [*CUSTOMERS, *ACCOUNTS, 'PRIVATE'])


def test_offline_workspace_contains_ten_transfers_and_the_original_three_alerts(client):
    response = client.post('/api/v1/workspace/refresh', json={})
    assert response.status_code == 200
    data = response.json()
    assert data['data_mode'] == 'synthetic'
    transfers = [row for row in data['transactions'] if row['kind'] == 'transfer']
    assert len(transfers) == 10 and len(data['transactions']) == 18
    assert {row['account_token'] for row in transfers} == {'acct_demo_a1'}
    assert len(client.get('/api/v1/alerts').json()) == 3
    for row in transfers:
        preview = client.get('/api/v1/privacy/preview/' + row['id'])
        assert preview.status_code == 200 and len(preview.json()['safe_payload']) == 8


@pytest.mark.parametrize('action', ['privacy', 'confirm', 'memories', 'delete', 'analysis', 'alerts'])
def test_nessie_failure_stops_original_customer_data_action(workspace, action):
    client, customers, behavior = workspace
    behavior['fail'].clear()
    behavior['overrides']['/transfers'] = []
    prefix = PREFIX + '/customers/' + customers[0]
    data = client.post(prefix + '/workspace/refresh', json={}).json()
    tx = next(row for row in data['transactions'] if row['kind'] == 'withdrawal')
    alert = client.get(prefix + '/alerts').json()[0]
    scope = hashlib.sha256(b'workspace-key').hexdigest()
    owner = 'demo-user-001:nessie:' + scope + ':' + customers[0]
    store = client.app.state.store
    memory = store.confirm(owner, 'separate-alert', 'normal', True, 'Sanitized category fact', 'test')
    paths = {'privacy': ('GET', '/privacy/preview/' + tx['id'], None),
             'confirm': ('POST', '/alerts/' + alert['alert_id'] + '/confirmations',
                         {'decision': 'normal', 'consent_to_memory': True}),
             'memories': ('GET', '/memories', None),
             'delete': ('DELETE', '/memories/' + memory.memory_id, None),
             'analysis': ('POST', '/analyses', {'transaction_id': tx['id']}),
             'alerts': ('GET', '/alerts', None)}
    behavior['calls'].clear()
    behavior['fail'].add('/accounts')
    method, path, body = paths[action]
    response = client.request(method, prefix + path, headers={'content-type': 'application/json'},
                              **({'json': body} if body else {}))
    assert response.status_code == 502
    assert response.json()['error']['code'] == 'nessie_unavailable'
    assert behavior['calls'] == [('GET', '/customers/' + CUSTOMERS[0] + '/accounts')]
    assert store.status(owner, alert['alert_id']) == 'open'
    assert len(store.list_memories(owner)) == 1
