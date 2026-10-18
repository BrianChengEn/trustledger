from datetime import date
import sqlite3

import pytest

from app.core.dataset_store import DatasetStore
from app.schemas.dataset import TransactionRecord


def transaction(**changes):
    values = dict(
        id='txn_test', owner='owner-a', source='nessie', dataset_id='sandbox-v1',
        source_record_key='txn_test', customer_token='customer_local',
        account_token='acct_local', amount_minor=18000, currency='USD', kind='withdrawal',
        direction='debit', occurred_date=date(2026, 10, 17))
    return TransactionRecord(**(values | changes))


def test_source_store_roundtrip_is_scoped_idempotent_and_preserves_unknowns(tmp_path):
    path = tmp_path / 'nessie.db'
    store = DatasetStore(path, 'nessie')
    row = transaction()
    store.upsert_transactions([row])
    store.upsert_transactions([row])
    restored = DatasetStore(path, 'nessie').list_transactions('owner-a')
    assert restored == [row]
    assert store.list_transactions('owner-b') == []
    assert restored[0].occurred_at is None
    assert restored[0].merchant_display is None
    assert restored[0].is_subscription is None
    with pytest.raises(ValueError, match='source'):
        DatasetStore(path, 'banksim')


def test_batch_rolls_back_on_identity_or_source_conflicts(tmp_path):
    store = DatasetStore(tmp_path / 'nessie.db', 'nessie')
    row = transaction()
    store.upsert_transactions([row])
    changed = row.model_copy(update={'dataset_id': 'different'})
    with pytest.raises(ValueError, match='identity'):
        store.upsert_transactions([transaction(id='txn_second', source_record_key='second'), changed])
    assert store.list_transactions('owner-a') == [row]
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_transactions([transaction(id='txn_collision')])
    with pytest.raises(ValueError, match='source'):
        store.upsert_transactions([transaction(source='banksim', occurred_date=None, simulation_step=1)])
    assert store.list_transactions('owner-a') == [row]


def test_predictions_reviews_and_failed_calls_remain_distinct(tmp_path):
    store = DatasetStore(tmp_path / 'nessie.db', 'nessie')
    store.upsert_transactions([transaction()])
    store.create_analysis_run('run-a', 'sandbox-v1', 'jev', 'jev-test',
                              'pattern != none', '2026-10-18T08:00:00+00:00')
    store.save_prediction('run-a', 'owner-a', 'txn_test', predicted_positive=True)
    store.save_review('owner-a', 'txn_test', 'normal', False, '2026-10-18T09:00:00+00:00')
    assert store.list_predictions('run-a', 'owner-a')[0]['predicted_positive'] == 1
    assert store.list_predictions('run-a', 'owner-b') == []
    with pytest.raises(ValueError):
        store.save_prediction('run-a', 'owner-a', 'txn_test', predicted_positive=False, status='failed')
    with pytest.raises(ValueError):
        store.save_prediction('run-a', 'owner-a', 'txn_test', predicted_positive=True, score=float('nan'))
    with pytest.raises(sqlite3.IntegrityError):
        store.save_prediction('run-a', 'owner-b', 'txn_test', predicted_positive=False)
    store.create_analysis_run('run-b', 'other-dataset', 'jev', 'jev-test',
                              'pattern != none', '2026-10-18T08:00:00+00:00')
    with pytest.raises(ValueError, match='dataset'):
        store.save_prediction('run-b', 'owner-a', 'txn_test', predicted_positive=True)
    with store.connect() as db:
        review = db.execute('SELECT decision,consent FROM human_reviews').fetchone()
        assert tuple(review) == ('normal', 0)
        assert not any('fraud' in r['name'] for r in db.execute('PRAGMA table_info(transactions)'))


def test_nessie_snapshot_reconciles_membership_preserves_review_and_orders_real_instants(tmp_path):
    store = DatasetStore(tmp_path / 'nessie.db', 'nessie')
    row = transaction()
    status = dict(account_token='', kind='accounts', requested_at='2026-10-18T08:00:00Z',
                  synced_at='2026-10-18T08:00:00Z', http_status=200, error=None)
    store.sync_nessie_snapshot('owner-a', [row], [status], '2026-10-18T08:00:00Z')
    store.save_review('owner-a', row.id, 'normal', False, '2026-10-18T08:10:00Z')
    assert store.source_page('owner-a')[1:3] == (1, 'cached')
    # 04:30 at UTC-4 is newer than 08:00 UTC, despite the smaller clock string.
    store.sync_nessie_snapshot('owner-a', [], [status], '2026-10-18T04:30:00-04:00')
    assert store.source_page('owner-a')[1] == 0
    store.sync_nessie_snapshot('owner-a', [row], [status], '2026-10-18T08:15:00Z')
    assert store.source_page('owner-a')[1] == 0
    assert store.list_transactions('owner-a') == [row]
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM human_reviews').fetchone()[0] == 1
    with pytest.raises(ValueError):
        store.sync_nessie_snapshot('owner-b', [row], [status], '2026-10-18T09:00:00Z')
    with pytest.raises(ValueError):
        store.source_page()
    with pytest.raises(ValueError):
        store.sync_nessie_snapshot('owner-a', [row], [status], '2026-10-18T10:00:00')
