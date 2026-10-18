from fastapi.testclient import TestClient

from app.adapters.account_demo import build_account_demo
from app.core.config import Settings
from app.main import create_app
from tests.unit.data.test_account_demo import inputs


def test_user_workspace_reads_same_100_nessie_ids_and_fields_as_source(tmp_path):
    csv_path, nessie_path = inputs(tmp_path)
    build_account_demo(csv_path, nessie_path, tmp_path / 'sources/account-demo', tmp_path / 'labels')
    code = 'acct_' + '0' * 32
    app = create_app(Settings(_env_file=None, database_path=tmp_path / 'product.db',
                             transaction_provider='account-demo', demo_account_token=code))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        source = client.get('/api/v1/data-sources/nessie/transactions',
                            params={'account_token': code, 'limit': 100}).json()['items']
        response = client.post('/api/v1/workspace/refresh', json={})
        assert response.status_code == 200
        view = response.json()
        rows = view['transactions']
        assert len(rows) == 100 and len({row['id'] for row in rows}) == 100
        assert view['data_mode'] == 'synthetic' and view['customer_id'] is None
        originals = {row['id']: row for row in source}
        assert set(originals) == {row['id'] for row in rows}
        for row in rows:
            original = originals[row['id']]
            assert row['account_token'] == original['account_token'] == code
            assert row['amount'] == original['amount_minor'] / 100
            assert row['currency'] == original['currency'] == 'USD'
            assert row['direction'] == original['direction']
            assert row['kind'] == original['kind']
            assert row['settlement_status'] == original['settlement_status']
            assert row['date_only'] is True
            assert row['occurred_at'] == original['occurred_date'] + 'T00:00:00Z'
            assert row['merchant_display'] == 'Transfer' and row['merchant_category'] == 'other'
            assert row['is_subscription'] is False
        history = client.get('/api/v1/transactions?limit=100').json()
        assert {row['id'] for row in history} == set(originals)
        health = client.get('/api/v1/health').json()
        assert health['data_mode'] == 'synthetic'
        assert client.get('/api/v1/alerts').status_code == 200
        assert client.get('/api/v1/privacy/preview/' + rows[0]['id']).status_code == 200
        assert client.post('/api/v1/analyses', json={'transaction_id': rows[0]['id']}).status_code == 200
        other = client.get('/api/v1/data-sources/nessie/transactions',
                           params={'account_token': 'acct_' + '1' * 32}).json()['items'][0]['id']
        assert client.post('/api/v1/analyses', json={'transaction_id': other}).status_code == 404
        assert not any(word in response.text for word in ('owner', 'fraud', 'label_origin', 'source_record_key'))


def test_account_demo_requires_explicit_valid_selection_and_fails_closed(tmp_path):
    import pytest
    from pydantic import ValidationError
    for value in (None, 'raw-account-id'):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, transaction_provider='account-demo', demo_account_token=value)
    csv_path, nessie_path = inputs(tmp_path)
    target = tmp_path / 'sources/account-demo'
    build_account_demo(csv_path, nessie_path, target, tmp_path / 'labels')
    from app.core.account_dataset import AccountDataset
    banksim = AccountDataset(target / 'banksim.db', 'banksim').accounts(limit=1)[0][0]['account_token']
    for code in ('acct_' + 'f' * 32, banksim):
        app = create_app(Settings(_env_file=None, database_path=tmp_path / 'product.db',
                                 transaction_provider='account-demo', demo_account_token=code))
        with TestClient(app, base_url='http://127.0.0.1') as client:
            assert client.post('/api/v1/workspace/refresh', json={}).status_code == 503
    store = AccountDataset(target / 'nessie.db', 'nessie')
    with store.connect() as db:
        db.execute('DELETE FROM account_origins WHERE transaction_id=(SELECT min(id) FROM transactions)')
        db.execute('DELETE FROM transactions WHERE id=(SELECT min(id) FROM transactions)')
    app = create_app(Settings(_env_file=None, database_path=tmp_path / 'product.db',
                             transaction_provider='account-demo', demo_account_token='acct_' + '0' * 32))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert client.post('/api/v1/workspace/refresh', json={}).status_code == 503


def test_account_demo_user_gate_and_memory_scope_follow_selected_account(tmp_path):
    csv_path, nessie_path = inputs(tmp_path)
    build_account_demo(csv_path, nessie_path, tmp_path / 'sources/account-demo', tmp_path / 'labels')
    from app.core.account_dataset import AccountDataset
    account = AccountDataset(tmp_path / 'sources/account-demo/nessie.db', 'nessie')
    with account.connect() as db:
        db.execute("UPDATE transactions SET direction='debit',amount_minor=84900 WHERE account_token=?",
                   ('acct_' + '0' * 32,))
    for digit in ('0', '1'):
        app = create_app(Settings(_env_file=None, database_path=tmp_path / 'product.db', require_login=True,
                                 demo_user_passcode='user-pass', allow_memory_write=True, transaction_provider='account-demo',
                                 demo_account_token='acct_' + digit * 32))
        with TestClient(app, base_url='http://127.0.0.1') as client:
            assert client.post('/api/v1/workspace/refresh', json={}).status_code == 401
            assert client.post('/api/v1/auth/login', json={'role': 'user', 'passcode': 'user-pass'}).status_code == 200
            rows = client.post('/api/v1/workspace/refresh', json={}).json()['transactions']
            assert len(rows) == 100 and {row['account_token'] for row in rows} == {'acct_' + digit * 32}
            assert client.get('/api/v1/data-sources/nessie/accounts').status_code == 403
            if digit == '0':
                first_ids = {row['id'] for row in rows}
                alert = client.get('/api/v1/alerts').json()[0]
                confirmed = client.post('/api/v1/alerts/' + alert['alert_id'] + '/confirmations',
                                        json={'decision': 'normal', 'consent_to_memory': True})
                assert confirmed.status_code == 200 and confirmed.json()['memory_status'] == 'written'
                assert len(client.get('/api/v1/memories').json()) == 1
            else:
                assert first_ids.isdisjoint(row['id'] for row in rows)
                assert client.get('/api/v1/memories').json() == []


def test_account_workspace_preserves_timestamp_and_explicit_source_values(tmp_path):
    from app.core.dataset_store import DatasetStore
    from datetime import datetime, timezone
    csv_path, nessie_path = inputs(tmp_path)
    original = DatasetStore(nessie_path, 'nessie')
    template = original.list_transactions('owner-0')[0]
    timestamp = datetime(2026, 10, 18, 13, 45, tzinfo=timezone.utc)
    original.upsert_transactions([template.model_copy(update={
        'occurred_date': None, 'occurred_at': timestamp, 'merchant_display': 'Known merchant',
        'merchant_category': 'groceries', 'is_subscription': True, 'settlement_status': 'pending',
        'kind': 'purchase', 'direction': 'debit'})])
    build_account_demo(csv_path, nessie_path, tmp_path / 'sources/account-demo', tmp_path / 'labels')
    app = create_app(Settings(_env_file=None, database_path=tmp_path / 'product.db',
                             transaction_provider='account-demo', demo_account_token='acct_' + '0' * 32))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        rows = client.post('/api/v1/workspace/refresh', json={}).json()['transactions']
        assert len(rows) == 100
        for row in rows:
            assert row['occurred_at'] == '2026-10-18T13:45:00Z' and row['date_only'] is False
            assert row['merchant_display'] == 'Known merchant' and row['merchant_category'] == 'groceries'
            assert row['is_subscription'] is True and row['settlement_status'] == 'pending'
        assert client.get('/api/v1/alerts').json() == []
