from fastapi.testclient import TestClient

from app.adapters.account_demo import build_account_demo
from app.core.config import Settings
from app.core.dataset_store import DatasetStore
from app.main import create_app
from tests.unit.data.test_account_demo import inputs


def test_v3_relevant_memory_uses_selected_account_and_never_clears_alert(tmp_path):
    csv_path, nessie_path = inputs(tmp_path)
    templates = DatasetStore(nessie_path, 'nessie')
    for digit in ('0', '1'):
        row = templates.list_transactions('owner-' + digit)[0]
        templates.upsert_transactions([row.model_copy(update={'amount_minor': 84900, 'direction': 'debit'})])
    build_account_demo(csv_path, nessie_path, tmp_path / 'sources/account-demo', tmp_path / 'labels')
    saved = None
    for digit in ('0', '1', '0'):
        app = create_app(Settings(
            _env_file=None, database_path=tmp_path / 'product.db', allow_memory_write=True,
            transaction_provider='account-demo', demo_account_token='acct_' + digit * 32,
            backboard_api_key='', nessie_api_key='', jev_api_key='', gemini_api_key=''))
        with TestClient(app, base_url='http://127.0.0.1') as client:
            alert = client.get('/api/v1/alerts').json()[0]
            path = '/api/v1/transactions/' + alert['transaction_id'] + '/relevant-memories'
            relevant = client.get(path)
            assert relevant.status_code == 200
            if saved is None:
                assert relevant.json()['memories'] == []
                confirmed = client.post('/api/v1/alerts/' + alert['alert_id'] + '/confirmations',
                                        json={'decision': 'normal', 'consent_to_memory': True})
                assert confirmed.status_code == 200
                assert confirmed.json()['memory_status'] == 'written'
                saved = confirmed.json()['memory_id']
                relevant = client.get(path)
                assert relevant.json()['memories'][0]['source'] == 'local-fallback'
            elif digit == '1':
                assert relevant.json()['memories'] == []
                assert client.delete('/api/v1/memories/' + saved).status_code == 404
            else:
                assert relevant.json()['memories'][0]['memory_id'] == saved
                assert client.delete('/api/v1/memories/' + saved).status_code == 204
                assert client.get(path).json()['memories'] == []
            current = next(row for row in client.get('/api/v1/alerts').json()
                           if row['alert_id'] == alert['alert_id'])
            assert current['needs_human'] is True
            assert current['alert_type'] == alert['alert_type']
