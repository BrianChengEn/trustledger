"""Offline acceptance for the isolated pair and existing consent contracts."""
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.store import Store
from app.main import create_app

SENTENCE = ('The demo user explicitly confirmed a streaming alert as normal. '
            'Recheck future evidence.')
LAUNCHER = Path(__file__).resolve().parents[3] / 'scripts/dev-level2-backend.sh'

spec = importlib.util.spec_from_file_location(
    'seed_level2_pair', Path(__file__).resolve().parents[3] / 'scripts/seed_level2_pair.py')
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def test_isolation_idempotence_and_schema(tmp_path):
    protected = tmp_path / 'trustledger-demo.db'
    protected.write_bytes(b'untouched sentinel')
    with pytest.raises(ValueError):
        seed.prepare_database(protected)
    assert protected.read_bytes() == b'untouched sentinel'
    path = tmp_path / seed.DATABASE.name
    assert seed.prepare_database(path) == seed.prepare_database(path) == 19
    link = tmp_path / 'linked' / seed.DATABASE.name
    link.parent.mkdir()
    link.symlink_to(protected)
    with pytest.raises(ValueError):
        seed.prepare_database(link)
    store = Store(path)
    with store.connect() as db:
        assert len(db.execute('PRAGMA table_info(demo_transactions)').fetchall()) > 12
        assert db.execute('SELECT COUNT(*) FROM confirmations').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM memories').fetchone()[0] == 0
        db.execute("UPDATE demo_transactions SET amount_cents=1200 WHERE id='txn_syn_009'")
    with pytest.raises(ValueError, match='different values'):
        seed.prepare_database(path)


def test_pair_local_consent_retrieve_delete_contract(tmp_path):
    path = tmp_path / seed.DATABASE.name
    seed.prepare_database(path)
    settings = Settings(_env_file=None, database_path=path, allow_memory_write=True,
                        backboard_api_key='', gemini_api_key='', jev_api_key='', nessie_api_key='',
                        transaction_provider='synthetic', fraud_provider='rules-only')
    with TestClient(create_app(settings)) as client:
        url = '/api/v1/transactions/txn_syn_009/relevant-memories'
        empty = dict(memories=[], retrieval_mode='local_fallback', checked_at=None, failure=None)
        assert client.get(url).json() == empty
        assert client.get(url[:-1]).status_code == 404
        alerts = {a['transaction_id']: a for a in client.get('/api/v1/alerts').json()}
        for tid in ['txn_syn_004', 'txn_syn_009']:
            assert alerts[tid]['alert_type'] == 'duplicate'
            assert alerts[tid]['needs_human'] is True
        before = client.post('/api/v1/analyses', json={'transaction_id': 'txn_syn_009'}).json()
        response = client.post('/api/v1/alerts/alert_txn_syn_004/confirmations',
                               json={'decision': 'normal', 'consent_to_memory': True})
        assert response.status_code == 200
        receipt = response.json()
        mid = receipt['memory_id']
        assert receipt['memory_status'] == 'written' and mid
        listed = client.get('/api/v1/memories').json()
        assert [m['memory_id'] for m in listed] == [mid]
        body = client.get(url).json()
        assert body['retrieval_mode'] == 'local_fallback'
        assert body['memories'][0]['verification'] == 'local_only'
        assert body['memories'][0]['source'] == 'local-fallback'
        summary = body['memories'][0]['summary']
        assert summary == SENTENCE
        for forbidden in ('StreamWave', 'txn_syn', 'acct_', '11.99', '1199', 'demo-user'):
            assert forbidden not in summary
        second = next(a for a in client.get('/api/v1/alerts').json()
                      if a['transaction_id'] == 'txn_syn_009')
        assert second['alert_type'] == 'duplicate' and second['needs_human'] is True
        assert second['status'] == 'open' and second['alert_id'] == 'alert_txn_syn_009'
        after = client.post('/api/v1/analyses', json={'transaction_id': 'txn_syn_009'}).json()
        for field in ['severity', 'alert_type', 'needs_human']:
            assert after[field] == before[field]
        replay = client.post('/api/v1/alerts/alert_txn_syn_004/confirmations',
                             json={'decision': 'normal', 'consent_to_memory': True}).json()
        assert replay['memory_id'] == mid
        result = client.delete('/api/v1/memories/' + mid)
        assert result.status_code == 204 and result.content == b''
        assert client.get('/api/v1/memories').json() == []
        assert client.get(url).json() == empty
        verification = client.get('/api/v1/memories/' + mid + '/deletion-verification').json()
        assert verification == dict(memory_id=mid, status='unverified', checked_at=None,
                                    failure='reference_unavailable')


def test_level2_refuses_memory_without_consent(tmp_path):
    path = tmp_path / seed.DATABASE.name
    seed.prepare_database(path)
    settings = Settings(_env_file=None, database_path=path, allow_memory_write=True, app_env='test',
                        backboard_api_key='', gemini_api_key='', jev_api_key='', nessie_api_key='',
                        transaction_provider='synthetic', fraud_provider='rules-only')
    with TestClient(create_app(settings)) as client:
        response = client.post('/api/v1/alerts/alert_txn_syn_004/confirmations',
                               json={'decision': 'normal', 'consent_to_memory': False})
        assert response.status_code == 200
        body = response.json()
        assert body['memory_status'] == 'not-requested' and body['memory_id'] is None
        assert client.get('/api/v1/memories').json() == []
        later = client.get('/api/v1/transactions/txn_syn_009/relevant-memories').json()
        assert later['memories'] == [] and later['retrieval_mode'] == 'local_fallback'
        second = next(a for a in client.get('/api/v1/alerts').json()
                      if a['transaction_id'] == 'txn_syn_009')
        assert second['status'] == 'open' and second['needs_human'] is True


def test_launcher_stays_on_isolated_test_runtime(tmp_path, monkeypatch):
    text = LAUNCHER.read_text()
    assert text.index('export APP_ENV=test') < text.index('uvicorn')
    assert 'TRANSACTION_PROVIDER=synthetic' in text
    assert 'level2-similar-alerts.db' in text
    assert 'trustledger-demo.db' not in text
    assert "BACKBOARD_API_KEY=''" in text and "NESSIE_API_KEY=''" in text
    assert "NESSIE_CUSTOMER_ID=''" in text
    assert '--port 8001' in text and 'ALLOW_MEMORY_WRITE=true' in text
    monkeypatch.delenv('APP_ENV', raising=False)
    monkeypatch.delenv('TRANSACTION_PROVIDER', raising=False)
    path = tmp_path / 'level2-similar-alerts.db'
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env='development', transaction_provider='synthetic',
                 database_path=path, allow_memory_write=True)
    settings = Settings(_env_file=None, app_env='test', transaction_provider='synthetic',
                        database_path=path, allow_memory_write=True, backboard_api_key='',
                        nessie_api_key='', nessie_customer_id='')
    assert settings.transaction_provider == 'synthetic'
    assert settings.database_path.name == 'level2-similar-alerts.db'
    assert settings.backboard_api_key.get_secret_value() == ''
