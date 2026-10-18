from fastapi.testclient import TestClient

from app.adapters.account_demo import build_account_demo
from app.core.config import Settings
from app.main import create_app
from tests.unit.data.test_account_demo import inputs


def test_local_account_pages_use_same_public_schema_without_remote_keys(tmp_path):
    csv_path, nessie_path = inputs(tmp_path)
    build_account_demo(csv_path, nessie_path, tmp_path / 'sources/account-demo', tmp_path / 'labels')
    app = create_app(Settings(_env_file=None, database_path=tmp_path / 'product.db'))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        for source, currency, accounts in [('banksim','EUR',12),('nessie','USD',2)]:
            response = client.get(f'/api/v1/data-sources/{source}/accounts?limit=1')
            assert response.status_code == 200
            options = response.json()
            assert options['total'] == accounts and options['next_offset'] == 1
            account = options['items'][0]
            total = 110 if source == 'banksim' else 100
            assert account['transaction_count'] == total
            code = account['account_token']
            rows = client.get(f'/api/v1/data-sources/{source}/transactions?account_token={code}&limit=100').json()
            assert rows['total'] == total and len(rows['items']) == 100
            assert rows['data_mode'] == 'synthetic-derived'
            if source == 'banksim':
                assert rows['next_offset'] == 100
                last = client.get(f'/api/v1/data-sources/{source}/transactions?account_token={code}&limit=100&offset=100').json()
                assert len(last['items']) == 10 and last['next_offset'] is None
                assert len({row['id'] for row in rows['items'] + last['items']}) == total
            else:
                assert rows['next_offset'] is None
                assert {row['kind'] for row in rows['items']} == {'purchase', 'transfer', 'deposit', 'withdrawal'}
            assert all(row['account_token'] == code and row['currency'] == currency for row in rows['items'])
            assert not any('fraud' in str(row) or 'owner' in row for row in rows['items'])
            assert client.get(f'/api/v1/data-sources/{source}/accounts?q={account["label"]}').json()['total'] == 1
        assert client.get('/api/v1/data-sources/banksim/transactions').json()['total'] == 0
        assert len(client.get('/api/v1/transactions?limit=100').json()) == 18
        assert client.get('/api/v1/data-sources/banksim/transactions?account_token='+'acct_'+'f'*32).status_code == 404
        assert client.get('/api/v1/data-sources/banksim/transactions?account_token=raw-id').status_code == 422
        assert client.get('/api/v1/data-sources/banksim/accounts?limit=101').status_code == 422


def test_account_reads_keep_admin_gate_and_do_not_require_nessie_credentials(tmp_path):
    csv_path, nessie_path = inputs(tmp_path)
    build_account_demo(csv_path, nessie_path, tmp_path / 'sources/account-demo', tmp_path / 'labels')
    app = create_app(Settings(_env_file=None, database_path=tmp_path / 'product.db', require_login=True,
                             demo_user_passcode='user-pass', demo_admin_passcode='admin-pass'))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        path = '/api/v1/data-sources/nessie/accounts'
        assert client.get(path).status_code == 401
        assert client.post('/api/v1/auth/login', json={'role':'user','passcode':'user-pass'}).status_code == 200
        assert client.get(path).status_code == 403
        assert client.get('/api/v1/data-sources/nessie/transactions?account_token='+'acct_'+'0'*32).status_code == 403
        assert client.post('/api/v1/auth/login', json={'role':'admin','passcode':'admin-pass'}).status_code == 200
        code = client.get(path).json()['items'][0]['account_token']
        assert client.get('/api/v1/data-sources/nessie/transactions?account_token='+code).status_code == 200
        assert client.get('/api/v1/data-sources/banksim/transactions?account_token='+code).status_code == 404
