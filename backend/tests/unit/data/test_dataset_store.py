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
