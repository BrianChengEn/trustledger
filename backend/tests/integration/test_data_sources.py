from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.dataset_import import import_banksim
from app.core.config import Settings
from app.core.dataset_store import DatasetStore
from app.main import create_app


def test_banksim_sqlite_flows_to_paginated_api_without_labels_or_vendor_calls(tmp_path):
    source = tmp_path / 'banks.csv'
    source.write_text("step,customer,age,gender,zipcodeOri,merchant,zipMerchant,category,amount,fraud\n"
                      "120,'C1','2','F','28007','M123','28007','es_health',180.01,1\n"
                      "120,'C2','2','F','28007','M234','28007','es_food',0.29,0\n")
    store = DatasetStore(tmp_path / 'sources/banksim.db', 'banksim')
    import_banksim(source, store)
    app = create_app(Settings(_env_file=None, database_path=tmp_path / 'demo.db'))
    with TestClient(app, base_url='http://127.0.0.1', headers={'origin': 'http://localhost:5173'}) as client:
        page = client.get('/api/v1/data-sources/banksim/transactions?limit=1').json()
        assert page['total'] == 2 and page['next_offset'] == 1
        assert page['data_mode'] == 'research'
        row = page['items'][0]
        assert row['amount_minor'] == 18001 and row['currency'] == 'EUR'
        assert row['merchant_code'] == 'M123' and row['source_category'] == 'es_health'
        assert row['simulation_step'] == 120
        assert row['occurred_at'] is None and row['occurred_date'] is None
        assert row['merchant_display'] is None and row['is_subscription'] is None
        assert not {'fraud', 'ground_truth_fraud', 'owner', 'predicted_positive'} & row.keys()
        next_page = client.get('/api/v1/data-sources/banksim/transactions?limit=1&offset=1').json()
        assert next_page['items'][0]['amount_minor'] == 29 and next_page['next_offset'] is None
        assert client.post('/api/v1/data-sources/banksim/refresh', json={}).status_code == 404
        assert client.get('/api/v1/data-sources/other/transactions').status_code == 422
        assert client.get('/api/v1/data-sources/banksim/transactions?limit=101').status_code == 422
        assert client.get('/api/v1/data-sources/banksim/transactions?offset=-1').status_code == 422
        assert client.get('/api/v1/data-sources/banksim/transactions',
                          headers={'host': 'remote.example'}).status_code == 403
        assert client.post('/api/v1/data-sources/nessie/refresh', json={},
                           headers={'origin': 'https://foreign.example'}).status_code == 403
        assert len(client.get('/api/v1/transactions?limit=100').json()) == 18
    assert Path(tmp_path / 'sources/nessie.db').exists()
