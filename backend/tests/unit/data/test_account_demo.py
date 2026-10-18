import csv
import json
import sqlite3
from datetime import date

from app.adapters.account_demo import build_account_demo
from app.adapters.dataset_import import HEADER
from app.core.dataset_store import DatasetStore
from app.schemas.dataset import TransactionRecord


def inputs(tmp_path, *, bank_customers=12):
    path = tmp_path / 'banks.csv'
    with path.open('w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)
        for index in range(bank_customers * 110):
            writer.writerow([index % 180, f'C{index // 110}', '2', 'F', '28007',
                             'M1', '28007', 'es_health', '180.01', int(index < bank_customers * 2)])
    store = DatasetStore(tmp_path / 'original-nessie.db', 'nessie')
    for index in range(2):
        store.upsert_transactions([TransactionRecord(
            id=f'txn_{index}', owner=f'owner-{index}', source='nessie', dataset_id='nessie-cache-v1',
            source_record_key=f'template-{index}', account_token='acct_' + str(index) * 32,
            amount_minor=123 + index, currency='USD', kind='transfer', direction='unknown',
            occurred_date=date(2026, 10, 18), settlement_status='completed')])
    return path, store.filename


def test_generated_accounts_keep_100_rows_provenance_and_separate_offline_labels(tmp_path):
    csv_path, nessie_path = inputs(tmp_path)
    original = nessie_path.read_bytes()
    target, labels = tmp_path / 'account-demo', tmp_path / 'offline-labels'
    report = build_account_demo(csv_path, nessie_path, target, labels)
    assert report['banksim']['accounts'] == 12 and report['banksim']['transactions'] == 1200
    assert report['banksim']['fraud_samples'] == 15
    assert report['nessie']['accounts'] == 2 and report['nessie']['transactions'] == 200
    assert report['nessie']['fraud_samples'] == 2
    assert build_account_demo(csv_path, nessie_path, target, labels) == report
    assert nessie_path.read_bytes() == original
    other = tmp_path / 'replica'
    assert build_account_demo(csv_path, nessie_path, other, tmp_path / 'replica-labels') == report
    assert json.loads((other / 'manifest.json').read_text())['database_digests'] == json.loads((target / 'manifest.json').read_text())['database_digests']
    for source, expected, origin in [('banksim', 1200, 'banksim-ground-truth'),
                                     ('nessie', 200, 'simulated-allocation')]:
        manifest = [json.loads(line) for line in (labels / f'{source}.jsonl').read_text().splitlines()]
        assert len(manifest) == expected
        assert sum(row['fraud'] for row in manifest) == report[source]['fraud_samples']
        assert {row['label_origin'] for row in manifest} == {origin}
        with sqlite3.connect(target / f'{source}.db') as db:
            assert set(row[0] for row in db.execute('SELECT count(*) FROM transactions GROUP BY owner')) == {100}
            assert db.execute('SELECT count(*) FROM account_origins').fetchone()[0] == expected
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
            for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                assert not {'fraud', 'label_origin'} & {row[1] for row in db.execute(f'PRAGMA table_info({name})')}
            if source == 'banksim':
                assert db.execute('SELECT count(DISTINCT source_record_key) FROM account_origins').fetchone()[0] == 1200
                assert db.execute("SELECT count(*) FROM transactions WHERE currency='EUR' AND simulation_step IS NOT NULL AND occurred_date IS NULL AND amount_minor=18001").fetchone()[0] == 1200
            else:
                for owner, amount in db.execute('SELECT owner,min(amount_minor) FROM transactions GROUP BY owner'):
                    assert db.execute('SELECT count(DISTINCT amount_minor) FROM transactions WHERE owner=?',(owner,)).fetchone()[0] == 1
                assert db.execute("SELECT count(*) FROM transactions WHERE currency='USD' AND occurred_date='2026-10-18' AND simulation_step IS NULL AND direction='unknown'").fetchone()[0] == 200


def test_allocation_rejects_invalid_source_and_never_publishes_partial_batch(tmp_path):
    import pytest
    csv_path, nessie_path = inputs(tmp_path)
    target, labels = tmp_path / 'account-demo', tmp_path / 'offline-labels'
    with pytest.raises(ValueError, match='separate'):
        build_account_demo(csv_path, nessie_path, target, target / 'labels')
    with csv_path.open('a') as file:
        file.write('invalid,row\n')
    with pytest.raises(ValueError):
        build_account_demo(csv_path, nessie_path, target, labels)
    assert not target.exists() and not labels.exists()


def test_interrupted_publication_can_retry_matching_offline_labels(tmp_path, monkeypatch):
    from pathlib import Path
    import pytest
    csv_path, nessie_path = inputs(tmp_path)
    target, labels = tmp_path / 'account-demo', tmp_path / 'offline-labels'
    rename = Path.rename
    interrupted = False

    def interrupt_runtime_publish(path, destination):
        nonlocal interrupted
        if destination == target and not interrupted:
            interrupted = True
            raise OSError('simulated interrupted publication')
        return rename(path, destination)

    monkeypatch.setattr(Path, 'rename', interrupt_runtime_publish)
    with pytest.raises(OSError, match='interrupted publication'):
        build_account_demo(csv_path, nessie_path, target, labels)
    assert not target.exists() and labels.exists()
    assert build_account_demo(csv_path, nessie_path, target, labels)['banksim']['transactions'] == 1200
