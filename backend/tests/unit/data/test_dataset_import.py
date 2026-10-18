import csv
import sqlite3

import pytest

from app.adapters.dataset_import import import_banksim, import_nessie_cache
from app.core.dataset_store import DatasetStore
from app.core.store import Store

HEADER = ['step', 'customer', 'age', 'gender', 'zipcodeOri', 'merchant',
          'zipMerchant', 'category', 'amount', 'fraud']


def banksim_csv(path, *, invalid=False):
    with path.open('w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)
        writer.writerow([120, "'C1'", '2', 'F', '28007', "'M123'", '28007', "'es_health'", '180.00', 1])
        writer.writerow([120, "'C1'", '2', 'F', '28007', "'M123'", '28007', "'es_health'", '180.00',
                         'invalid' if invalid else 0])


def test_banksim_import_keeps_steps_duplicate_rows_and_no_labels(tmp_path):
    path = tmp_path / 'banks.csv'
    banksim_csv(path)
    store = DatasetStore(tmp_path / 'banksim.db', 'banksim')
    first = import_banksim(path, store)
    assert first['transactions'] == 2 and first['fraud_labels'] == 1
    assert import_banksim(path, store) == first
    with store.connect() as db:
        owner = db.execute('SELECT owner FROM transactions LIMIT 1').fetchone()[0]
        assert db.execute('SELECT count(*) FROM transactions').fetchone()[0] == 2
        assert not any('fraud' in row[1] for name in ['transactions', 'banksim_features']
                       for row in db.execute(f'PRAGMA table_info({name})'))
    rows = store.list_transactions(owner)
    assert len(rows) == 2 and rows[0].id != rows[1].id
    assert rows[0].amount_minor == 18000 and rows[0].currency == 'EUR'
    assert rows[0].simulation_step == 120 and rows[0].occurred_at is None
    assert rows[0].occurred_date is None and rows[0].account_token is None
    assert rows[0].merchant_display is None and rows[0].is_subscription is None
    assert rows[0].source_category == 'es_health'
    assert rows[0].banksim_features.merchant_code == 'M123'
    assert rows[0].banksim_features.customer_code == 'C1'
    assert len(store.list_transactions(owner, limit=1)) == 1
    assert store.list_transactions(owner, limit=1, offset=1) == [rows[1]]


def test_invalid_banksim_file_rolls_back_the_entire_import(tmp_path):
    path = tmp_path / 'banks.csv'
    banksim_csv(path, invalid=True)
    store = DatasetStore(tmp_path / 'banksim.db', 'banksim')
    with pytest.raises(ValueError):
        import_banksim(path, store)
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM transactions').fetchone()[0] == 0


def test_nessie_cache_import_preserves_ids_and_date_precision_without_writing_cache(tmp_path):
    source = Store(tmp_path / 'demo.db')
    source.save_workspace_collection('owner-a', '', 'accounts', [('acct_a', 'Checking', 10000, 0)],
                                     '2026-10-18T07:00:00+00:00', 200, None)
    source.save_workspace_collection('owner-a', 'acct_a', 'withdrawals',
        [('txn_a', 'acct_a', 'withdrawal', '2026-10-17T00:00:00+00:00', 1, 18000, 'debit', 'completed')],
        '2026-10-18T07:00:00+00:00', 200, None)
    before = source.filename.read_bytes()
    store = DatasetStore(tmp_path / 'nessie.db', 'nessie')
    assert import_nessie_cache(source.filename, store)['transactions'] == 1
    assert import_nessie_cache(source.filename, store)['transactions'] == 1
    assert source.filename.read_bytes() == before
    row = store.list_transactions('owner-a')[0]
    assert row.id == 'txn_a' and row.account_token == 'acct_a'
    assert row.occurred_date.isoformat() == '2026-10-17' and row.occurred_at is None
    assert row.merchant_display is None and row.merchant_category is None
    assert row.is_subscription is None and row.amount_minor == 18000
    with pytest.raises(ValueError, match='non-source'):
        DatasetStore(source.filename, 'nessie')
    assert source.filename.read_bytes() == before
    with sqlite3.connect(source.filename) as db:
        assert db.execute('SELECT count(*) FROM workspace_movements').fetchone()[0] == 1


def test_missing_nessie_sync_metadata_does_not_commit_transactions(tmp_path):
    source = Store(tmp_path / 'malformed.db')
    source.save_workspace_collection('owner-a', '', 'accounts', [('acct_a', 'Checking', 10000, 0)],
                                     '2026-10-18T07:00:00+00:00', 200, None)
    source.save_workspace_collection('owner-a', 'acct_a', 'withdrawals',
        [('txn_a', 'acct_a', 'withdrawal', '2026-10-17T00:00:00+00:00', 1, 18000, 'debit', 'completed')],
        '2026-10-18T07:00:00+00:00', 200, None)
    with source.connect() as db:
        db.execute('DROP TABLE workspace_sync')
    store = DatasetStore(tmp_path / 'nessie.db', 'nessie')
    with pytest.raises(sqlite3.OperationalError):
        import_nessie_cache(source.filename, store)
    assert store.list_transactions('owner-a') == []
