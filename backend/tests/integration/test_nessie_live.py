"""Opt-in read-only Nessie verification; isolated SQLite, no remote AI/memory calls.

Run NESSIE_LIVE_TEST=1 pytest -s tests/integration/test_nessie_live.py.
Unlike MockTransport tests, this uses the configured Nessie HTTPS adapter.
"""
import json
from hashlib import sha256
import os

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.adapters.nessie import NessieClient
from app.core.config import Settings
from app.main import create_app
from app.services.workspace import collection, movements, token

pytestmark = pytest.mark.live_network


def test_real_nessie_to_fastapi_readonly(tmp_path):
    if os.environ.get('NESSIE_LIVE_TEST') != '1':
        pytest.skip('Set NESSIE_LIVE_TEST=1 for actual read-only Nessie HTTPS verification')
    settings = Settings(transaction_provider='nessie', app_env='development',
                        database_path=tmp_path / 'nessie-live.db', source_database_dir=tmp_path / 'sources',
                        demo_user_id='isolated-nessie-verification', require_login=True,
                        demo_user_passcode=SecretStr('local-verification-only'),
                        backboard_api_key='', gemini_api_key='', jev_api_key='',
                        fraud_provider='rules-only', allow_memory_write=False, allow_demo_edit=False)
    if not settings.nessie_api_key.get_secret_value() or not settings.nessie_customer_id.get_secret_value():
        pytest.fail('Live Nessie verification requires configured backend key and sandbox customer')
    app = create_app(settings)
    captures = []
    original = NessieClient.request

    def observed(self, method, path, payload=None):
        assert method == 'GET', 'Live verification permits GET only'
        assert len(captures) < 100, 'Live verification request budget exceeded'
        result = original(self, method, path, payload)
        captures.append((path, result))
        return result

    app.state.nessie.request = lambda method, path, payload=None: observed(app.state.nessie, method, path, payload)
    with TestClient(app) as client:
        assert client.get('/api/v1/transactions').status_code == 401
        assert client.post('/api/v1/auth/login', json={
            'role': 'user', 'passcode': 'local-verification-only'}).status_code == 200
        first = client.get('/api/v1/transactions?limit=100')
        if first.status_code != 200:
            safe = [{'http_status': c['http_status'], 'transport_error': c['transport_error']}
                    for _, c in captures]
            pytest.fail('Live backend read failed: ' + json.dumps(safe))
        rows = first.json()
        assert bool(rows), 'Live read succeeded but no transactions exist; nonempty chain is unverified'
        assert first.headers['X-Transaction-Upstream-Status'] == 'live'
        assert first.headers['X-Transaction-Fallback-Used'] == 'false'
        assert all(row['source'] == 'nessie' and not row['id'].startswith('txn_syn') for row in rows)
        # Compare actual wire records to deterministic account/transaction projection, in memory only.
        scope = sha256(settings.nessie_api_key.get_secret_value().encode()).hexdigest()
        customer = settings.nessie_customer_id.get_secret_value()
        code = app.state.store.alias_resources(settings.demo_user_id, scope, 'customer', [customer])[customer]
        owner = f'{settings.demo_user_id}:nessie:{scope}:{code}'
        expected = {}
        for path, capture in captures:
            if path.startswith('/accounts/'):
                _, _, account, kind = path.split('/')
                for raw in collection(capture):
                    normalized, = movements([raw], owner, account, kind)
                    expected[normalized[0]] = normalized
                    assert normalized[0] == token('txn_', owner, kind + ':' + account + ':' + raw['_id'])
        assert all(row['id'] in expected for row in rows)
        assert all(row['account_token'] == expected[row['id']][1]
                   and round(row['amount'] * 100) == expected[row['id']][5]
                   and row['direction'] == expected[row['id']][6] for row in rows)
        repeated = client.get('/api/v1/transactions?limit=100')
        assert repeated.status_code == 200 and repeated.json() == rows
        snapshot = client.post('/api/v1/workspace/refresh', json={})
        assert snapshot.status_code == 200
        assert snapshot.headers.get('X-Transaction-Provider') == 'nessie-live'
        assert [r['id'] for r in snapshot.json()['transactions']] == [r['id'] for r in rows]
        tx = rows[0]['id']
        analysis = client.post('/api/v1/analyses', json={'transaction_id': tx})
        assert analysis.status_code == 200 and analysis.json()['transaction_id'] == tx
        if rows[0]['direction'] == 'unknown':
            assert 'Insufficient evidence' in analysis.json()['evidence'][0]
        privacy = client.get('/api/v1/privacy/preview/' + tx)
        assert privacy.status_code == 200 and privacy.json()['transaction_id'] == tx
        memories = client.get('/api/v1/transactions/' + tx + '/relevant-memories')
        assert memories.status_code == 200
        assert app.state.store.list_transactions(settings.demo_user_id) == []
        print(json.dumps({'verification': 'actual Nessie HTTPS to FastAPI', 'transaction_count': len(rows),
                          'stable_identity': True, 'wire_projection_matched': True,
                          'direction_counts': {direction: sum(r['direction'] == direction for r in rows) for direction in ('debit','credit','unknown')},
                          'at_or_above_250': sum(r['amount'] >= 250 for r in rows),
                          'settlement_counts': {status: sum(r['settlement_status'] == status for r in snapshot.json()['transactions']) for status in ('completed','pending','cancelled')},
                          'http_statuses': sorted({c['http_status'] for _, c in captures}),
                          'upstream_get_count': len(captures), 'fraud_privacy_relevant_memory': 'passed',
                          'synthetic_rows': 0, 'external_writes': 0}))
