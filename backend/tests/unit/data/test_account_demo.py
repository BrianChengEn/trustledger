import csv
import json
import sqlite3
from collections import Counter
from datetime import date

from app.adapters.account_demo import build_account_demo
from app.adapters.dataset_import import HEADER, banksim_rows
from app.core.dataset_store import DatasetStore
from app.schemas.dataset import TransactionRecord


def test_banksim_keeps_every_original_transaction_with_its_own_customer(tmp_path):
    from app.adapters.account_demo import digest
    from app.core.account_dataset import AccountDataset
    csv_path, nessie_path = inputs(tmp_path)
    originals = {row.id: row for row, _ in banksim_rows(csv_path, 'banksim:' + digest(csv_path))}
    target = tmp_path / 'v2'
    report = build_account_demo(csv_path, nessie_path, target, tmp_path / 'labels')
    assert report['banksim']['transactions'] == len(originals) == 1320
    store = AccountDataset(target / 'banksim.db', 'banksim')
    accounts, count = store.accounts(limit=100)
    assert count == 12
    seen = set()
    customers = set()
    for account in accounts:
        rows, total = store.account_page(account['account_token'], limit=100)
        rows += store.account_page(account['account_token'], limit=100, offset=100)[0]
        assert total == account['transaction_count'] == len(rows) == 110
        customer = {row.customer_token for row in rows}
        assert len(customer) == 1 and customers.isdisjoint(customer)
        customers.update(customer)
        for row in rows:
            assert row.id not in seen
            seen.add(row.id)
            assert row.model_dump(exclude={'owner', 'account_token'}) == originals[row.id].model_dump(exclude={'owner', 'account_token'})
    assert seen == set(originals)


def test_nessie_uses_source_probabilities_and_marks_missing_kind_templates(tmp_path):
    from app.core.account_dataset import AccountDataset
    csv_path, nessie_path = inputs(tmp_path)
    original = DatasetStore(nessie_path, 'nessie')
    base = original.list_transactions('owner-0')[0]
    for kind, count in [('purchase', 1), ('transfer', 178), ('deposit', 48), ('withdrawal', 48)]:
        original.upsert_transactions([base.model_copy(update={
            'id': f'template_{kind}_{index}', 'source_record_key': f'{kind}-{index}', 'kind': kind})
            for index in range(count)])
    target = tmp_path / 'v2'
    build_account_demo(csv_path, nessie_path, target, tmp_path / 'labels')
    store = AccountDataset(target / 'nessie.db', 'nessie')
    expected = {'purchase': 1, 'transfer': 63, 'deposit': 18, 'withdrawal': 18}
    for digit in ('0', '1'):
        code = 'acct_' + digit * 32
        rows, total = store.account_page(code, limit=100)
        assert total == 100 and dict(Counter(row.kind for row in rows)) == expected
        assert {row.account_token for row in rows} == {code}
    manifest = json.loads((target / 'manifest.json').read_text())
    assert manifest['nessie_distribution']['source_counts'] == {
        'purchase': 1, 'transfer': 180, 'deposit': 48, 'withdrawal': 48}
    assert manifest['nessie_distribution']['per_account_counts'] == expected
    with store.connect() as db:
        for origin in db.execute('SELECT t.account_token,t.kind,o.source_dataset_id,o.source_owner '
                                 'FROM transactions t JOIN account_origins o '
                                 'ON o.owner=t.owner AND o.transaction_id=t.id'):
            assert origin['source_owner'] == ('owner-0' if origin['account_token'] == 'acct_' + '0' * 32 else 'owner-1')
            simulated = origin['account_token'] == 'acct_' + '1' * 32 and origin['kind'] != 'transfer'
            assert (origin['source_dataset_id'] == 'nessie-synthetic-kinds-v1') == simulated


def test_banksim_accounts_retain_short_and_long_source_histories(tmp_path):
    from app.core.account_dataset import AccountDataset
    csv_path, nessie_path = inputs(tmp_path)
    with csv_path.open('w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)
        for customer, count in [('Cshort', 5), ('Clong', 265)]:
            for index in range(count):
                writer.writerow([index % 180, customer, '2', 'F', '28007', 'M1', '28007',
                                 'es_health', '180.01', int(index < 2)])
    target = tmp_path / 'v2'
    report = build_account_demo(csv_path, nessie_path, target, tmp_path / 'labels')
    assert report['banksim'] == {'accounts': 2, 'transactions': 270, 'fraud_samples': 4}
    store = AccountDataset(target / 'banksim.db', 'banksim')
    accounts, _ = store.accounts(limit=100)
    assert sorted(account['transaction_count'] for account in accounts) == [5, 265]
    for account in accounts:
        rows = []
        for offset in range(0, account['transaction_count'], 100):
            rows.extend(store.account_page(account['account_token'], limit=100, offset=offset)[0])
        assert len(rows) == len({row.id for row in rows}) == account['transaction_count']
        assert len({row.banksim_features.customer_code for row in rows}) == 1


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
    assert report['banksim']['accounts'] == 12 and report['banksim']['transactions'] == 1320
    assert report['banksim']['fraud_samples'] == 24
    assert report['nessie']['accounts'] == 2 and report['nessie']['transactions'] == 200
    assert report['nessie']['fraud_samples'] == 2
    assert build_account_demo(csv_path, nessie_path, target, labels) == report
    assert nessie_path.read_bytes() == original
    other = tmp_path / 'replica'
    assert build_account_demo(csv_path, nessie_path, other, tmp_path / 'replica-labels') == report
    assert json.loads((other / 'manifest.json').read_text())['database_digests'] == json.loads((target / 'manifest.json').read_text())['database_digests']
    for source, expected, origin in [('banksim', 1320, 'banksim-ground-truth'),
                                     ('nessie', 200, 'simulated-allocation')]:
        manifest = [json.loads(line) for line in (labels / f'{source}.jsonl').read_text().splitlines()]
        assert len(manifest) == expected
        assert sum(row['fraud'] for row in manifest) == report[source]['fraud_samples']
        assert {row['label_origin'] for row in manifest} == {origin}
        with sqlite3.connect(target / f'{source}.db') as db:
            assert set(row[0] for row in db.execute('SELECT count(*) FROM transactions GROUP BY owner')) == {110 if source == 'banksim' else 100}
            assert db.execute('SELECT count(*) FROM account_origins').fetchone()[0] == expected
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
            for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                assert not {'fraud', 'label_origin'} & {row[1] for row in db.execute(f'PRAGMA table_info({name})')}
            if source == 'banksim':
                assert db.execute('SELECT count(DISTINCT source_record_key) FROM account_origins').fetchone()[0] == 1320
                assert db.execute("SELECT count(*) FROM transactions WHERE currency='EUR' AND simulation_step IS NOT NULL AND occurred_date IS NULL AND amount_minor=18001").fetchone()[0] == 1320
            else:
                for owner, amount in db.execute('SELECT owner,min(amount_minor) FROM transactions GROUP BY owner'):
                    assert db.execute('SELECT count(DISTINCT amount_minor) FROM transactions WHERE owner=?',(owner,)).fetchone()[0] == 1
                assert db.execute("SELECT count(*) FROM transactions WHERE currency='USD' AND occurred_date='2026-10-18' AND simulation_step IS NULL").fetchone()[0] == 200
                assert dict(db.execute('SELECT kind,count(*) FROM transactions GROUP BY kind')) == {'purchase': 2, 'transfer': 194, 'deposit': 2, 'withdrawal': 2}


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
    assert build_account_demo(csv_path, nessie_path, target, labels)['banksim']['transactions'] == 1320
