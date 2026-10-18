import csv
import gzip
import importlib
import json
from pathlib import Path
import subprocess
import sys
import sqlite3
import zipfile

import pytest

from app.adapters.account_demo import digest
from app.adapters.dataset_import import HEADER, banksim_rows, local_token
from app.core.account_dataset import AccountDataset


@pytest.fixture
def sidecar(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4]))
    module = importlib.import_module('evaluation.banksim_labels')
    source = tmp_path / 'original.csv'
    with source.open('w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)
        writer.writerows([[0, 'C1', '2', 'F', '28007', 'M1', '28007', 'es_health', '12.34', 0],
                          [1, 'C1', '2', 'F', '28007', 'M1', '28007', 'es_health', '12.34', 1]])
    dataset = 'banksim:' + digest(source)
    store = AccountDataset(tmp_path / 'banksim.db', 'banksim')
    labels = tmp_path / 'banksim.jsonl'
    originals = list(banksim_rows(source, dataset))
    customer = originals[0][0].owner
    account = local_token('acct_', dataset, customer)
    with store.connect() as db, labels.open('w') as file:
        db.execute('INSERT INTO accounts VALUES(?,?,?,?)', (account, 'test-owner', 'Test', customer))
        store._upsert(db, [row.model_copy(update={'owner': 'test-owner', 'account_token': account})
                           for row, _ in originals])
        for row, fraud in originals:
            db.execute('INSERT INTO account_origins VALUES(?,?,?,?,?)',
                       ('test-owner', row.id, dataset, row.source_record_key, row.owner))
            file.write(json.dumps({'id': row.id, 'account_token': account, 'fraud': fraud,
                                   'label_origin': 'banksim-ground-truth'}) + '\n')
    archive = tmp_path / 'release.zip'

    def seal():
        manifest = {'inputs': {'banksim': digest(source), 'version': 'account-demo-v3'},
                    'label_digests': {'banksim': digest(labels)},
                    'report': {'banksim': {'transactions': 2, 'fraud_samples': 1}}}
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('account-demo/manifest.json', json.dumps(manifest))
            bundle.writestr('DATASET-INFO.json', json.dumps({
                'database_digests': {'banksim': digest(store.filename)}}))
        monkeypatch.setattr(module, 'RELEASE_SHA256', digest(archive))

    seal()
    monkeypatch.setattr(module, 'EXPECTED_SHA256', digest(source))
    monkeypatch.setattr(module, 'EXPECTED_ROWS', 2)
    monkeypatch.setattr(module, 'EXPECTED_POSITIVES', 1)
    output = tmp_path / 'sidecar-v1'
    args = (store.filename, source, labels, archive, output)
    return module.export_sidecar, args, seal


def test_sidecar_preserves_ground_truth_and_database_bytes(sidecar):
    export, args, _ = sidecar
    before = args[0].read_bytes()
    report = export(*args)
    assert report['transactions'] == 2 and report['fraud_positives'] == 1
    assert report['coverage'] == 1 and report['unique_transaction_ids'] == 2
    assert gzip.decompress((args[-1] / 'banksim-ground-truth-v1.jsonl.gz').read_bytes()) == args[2].read_bytes()
    assert report['labels_sha256'] == digest(args[2])
    assert args[0].read_bytes() == before
    assert {p.name for p in args[-1].iterdir()} == {
        'banksim-ground-truth-v1.jsonl.gz', 'manifest.json', 'SHA256SUMS', 'LICENSE-BANKSIM.txt', 'USAGE.txt'}
    with pytest.raises(FileExistsError):
        export(*args)


@pytest.mark.parametrize('change', ['missing', 'wrong-id', 'wrong-label', 'not-boolean', 'nessie'])
def test_invalid_labels_never_create_an_artifact(sidecar, change):
    export, args, seal = sidecar
    rows = [json.loads(line) for line in args[2].read_text().splitlines()]
    if change == 'missing':
        rows.pop()
    elif change == 'wrong-id':
        rows[1]['id'] = rows[0]['id']
    elif change == 'wrong-label':
        rows[1]['fraud'] = False
    elif change == 'not-boolean':
        rows[0]['fraud'] = 0
    else:
        rows[0]['label_origin'] = 'simulated-allocation'
    args[2].write_text(''.join(json.dumps(row) + '\n' for row in rows))
    seal()  # Even a matching manifest cannot make corrupt labels authoritative.
    with pytest.raises(ValueError, match='coverage|truth mismatch'):
        export(*args)
    assert not args[-1].exists()


@pytest.mark.parametrize('input_index', [0, 1, 2, 3])
def test_changed_input_is_rejected_before_output(sidecar, input_index):
    export, args, _ = sidecar
    with args[input_index].open('ab') as file:
        file.write(b'changed')
    with pytest.raises(ValueError, match='mismatch'):
        export(*args)
    assert not args[-1].exists()


def test_cli_runs_from_repository_root():
    root = Path(__file__).resolve().parents[4]
    result = subprocess.run([sys.executable, '-m', 'evaluation.banksim_labels', '--help'],
                            cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '--release-archive' in result.stdout


@pytest.mark.parametrize('sql', [
    "UPDATE account_origins SET source_record_key='wrong'",
    "UPDATE accounts SET source_owner='other-customer'",
    "UPDATE transactions SET account_token='acct_wrong'",
    "UPDATE banksim_features SET merchant_code='wrong'",
    "UPDATE transactions SET source_record_key='wrong' WHERE source_record_key='000000000002'",
])
def test_matching_digests_cannot_hide_wrong_provenance(sidecar, sql):
    export, args, seal = sidecar
    with sqlite3.connect(args[0]) as db:
        db.execute(sql)
    seal()
    with pytest.raises(ValueError, match='provenance|duplicate'):
        export(*args)
    assert not args[-1].exists()
