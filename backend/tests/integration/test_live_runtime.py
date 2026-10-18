"""Normal runtime uses read-only Nessie HTTP, never synthetic/cache fallback."""
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.adapters.nessie import NessieClient
from app.core.config import Settings
from app.main import create_app

CUSTOMER = 'c' * 24
ACCOUNT = 'a' * 24


def test_runtime_selection(monkeypatch):
    monkeypatch.delenv('TRANSACTION_PROVIDER', raising=False)
    monkeypatch.delenv('APP_ENV', raising=False)
    assert Settings(_env_file=None).transaction_provider == 'nessie'
    for provider in ('synthetic', 'account-demo'):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, transaction_provider=provider)


@pytest.fixture
def live(tmp_path):
    settings = Settings(_env_file=None, app_env='production', transaction_provider='nessie',
                        database_path=tmp_path / 'live.db', nessie_api_key='private-key',
                        nessie_customer_id=CUSTOMER, backboard_api_key='', gemini_api_key='')
    app = create_app(settings)
    mode = {'failure': None, 'empty': False, 'no_accounts': False, 'calls': []}

    def upstream(request):
        assert request.method == 'GET'
        mode['calls'].append(request.url.path)
        assert request.url.params['key'] == 'private-key'
        if mode['failure'] == 'timeout':
            raise httpx.ReadTimeout('private-key secret upstream URL')
        if mode['failure'] == 'http':
            return httpx.Response(401, text='private-key sensitive body')
        if mode['failure'] == 'schema':
            return httpx.Response(200, json={'secret': 'private-key'})
        if request.url.path.endswith('/accounts'):
            rows = [] if mode['no_accounts'] else [{'_id': ACCOUNT, 'customer_id': CUSTOMER,
                    'type': 'Checking', 'balance': 10, 'rewards': 0}]
        elif request.url.path.endswith('/purchases') and not mode['empty']:
            rows = [{'_id': 'e' * 24, 'transaction_date': '2026-10-17',
                     'amount': 849, 'status': 'completed'}]
        else:
            rows = []
        return httpx.Response(200, json=rows)

    app.state.nessie = NessieClient('private-key', transport=httpx.MockTransport(upstream))
    with TestClient(app) as client:
        yield client, mode


def test_normal_runtime_normalization_analysis_and_provenance(live):
    client, mode = live
    response = client.get('/api/v1/transactions')
    assert response.status_code == 200
    assert response.headers['X-Transaction-Provider'] == 'nessie-live'
    assert response.headers['X-Transaction-Upstream-Status'] == 'live'
    assert response.headers['X-Transaction-Fallback-Used'] == 'false'
    tx, = response.json()
    assert tx['source'] == 'nessie' and tx['amount'] == 849 and tx['kind'] == 'purchase'
    assert tx['id'].startswith('txn_') and not tx['id'].startswith('txn_syn')
    assert all(value not in response.text for value in ('private-key', CUSTOMER, ACCOUNT))
    workspace = client.post('/api/v1/workspace/refresh', json={}).json()
    assert workspace['transactions'][0]['id'] == tx['id']
    analysis = client.post('/api/v1/analyses', json={'transaction_id': tx['id']})
    assert analysis.status_code == 200 and analysis.json()['transaction_id'] == tx['id']
    assert client.app.state.store.list_transactions('demo-user-001') == []
    assert len(mode['calls']) >= 5


@pytest.mark.parametrize('failure', ['timeout', 'http', 'schema'])
def test_failure_never_serves_cache_or_synthetic(live, failure):
    client, mode = live
    assert client.get('/api/v1/transactions').status_code == 200
    mode['failure'] = failure
    response = client.get('/api/v1/transactions')
    assert response.status_code == 502 and response.json()['error']['code'] == 'nessie_unavailable'
    assert response.headers['X-Transaction-Upstream-Status'] == 'unavailable'
    assert response.headers['X-Transaction-Fallback-Used'] == 'false'
    assert 'private-key' not in response.text and CUSTOMER not in response.text
    assert client.post('/api/v1/analyses', json={'transaction_id': 'txn_syn_004'}).status_code == 502


@pytest.mark.parametrize('empty', ['empty', 'no_accounts'])
def test_empty_success_does_not_fall_back(live, empty):
    client, mode = live
    assert client.get('/api/v1/transactions').json()
    mode[empty] = True
    response = client.get('/api/v1/transactions')
    assert response.status_code == 200 and response.json() == []
    assert response.headers['X-Transaction-Upstream-Status'] == 'live'


def test_missing_key_is_typed_unavailable(live):
    client, mode = live
    from pydantic import SecretStr
    client.app.state.settings.nessie_api_key = SecretStr('')
    response = client.get('/api/v1/transactions')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'nessie_not_configured'
    assert response.headers['X-Transaction-Upstream-Status'] == 'unavailable'
    assert not mode['calls']


def test_key_alone_does_not_select_customer_or_claim_live(live):
    from pydantic import SecretStr
    client, mode = live
    client.app.state.settings.nessie_customer_id = SecretStr('')
    response = client.get('/api/v1/transactions')
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'workspace_not_linked'
    assert response.headers['X-Transaction-Upstream-Status'] == 'unavailable'
    assert not mode['calls']


def test_generated_account_datasets_are_unavailable_in_normal_runtime(live):
    from app.services.data_sources import account_store
    from starlette.requests import Request
    client, _ = live
    request = Request({'type': 'http', 'app': client.app})
    # Even an already-cached generated store cannot bypass the runtime gate.
    client.app.state.account_stores['nessie'] = object()
    assert account_store(request, 'nessie') is None
