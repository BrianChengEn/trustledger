"""Package verified BankSim ground truth separately from runtime transaction databases.

Run from the repository root with backend/.venv/bin/python -m evaluation.banksim_labels.
No network calls, runtime imports of this module, or database writes are required.
"""
import argparse
from contextlib import closing
import gzip
import json
from itertools import zip_longest
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.adapters.account_demo import digest  # noqa: E402
from app.adapters.dataset_import import banksim_rows, local_token  # noqa: E402
from scripts.prepare_research_data import EXPECTED_SHA256  # noqa: E402

EXPECTED_ROWS = 594643
EXPECTED_POSITIVES = 7200
RELEASE_TAG = 'dataset-2026-10-18-v3'
RELEASE_SHA256 = 'd3ab5139fa2af6f45958c71600f88df1d19e0e7cfaa6db9603430b5f400843f5'
LICENSE = '''BankSim original fraud ground truth; TrustLedger transaction-label sidecar v1.
Authors: Edgar Alonso Lopez-Rojas and Stefan Axelsson (BankSim, EMSS 2014).
Source: https://www.kaggle.com/datasets/ealaxi/banksim1
License: CC BY-NC-SA 4.0, https://creativecommons.org/licenses/by-nc-sa/4.0/
Noncommercial use only; preserve attribution and share-alike terms.
Changes: source fraud values mapped to deterministic TrustLedger transaction IDs.
No Nessie simulated labels, predictions, rule alerts or product state are included.
Packaging and verification assisted by OpenAI Codex.
'''
USAGE = '''Offline research only. Verify SHA256SUMS before loading.
Decompress banksim-ground-truth-v1.jsonl.gz and verify labels_sha256 in manifest.json.
Join only BankSim transactions by exact id and account_token; require dataset_id
banksim:<source_csv_sha256>. IDs use the one-based original CSV row index, padded
to 12 digits: txn_ + SHA256(dataset_id + ':' + source_record_key)[:32].
Never join by amount, merchant or time. Missing labels are unknown, never false.
fraud is original BankSim ground truth; it is not a rule alert or model prediction.
Use in offline Fraud Intelligence Lab preparation; retain its frozen test split,
ranking protocol and saved score alignment. This sidecar supplies no model scores
and does not replace benchmark y arrays without verified source-row alignment.
Never attach these labels to Live Nessie transactions or expose through product APIs.
The archive is compatible with dataset-2026-10-18-v3 BankSim IDs; transaction
IDs also remain unchanged in the original normalized BankSim source database.
'''


def export_sidecar(database, truth_csv, labels, release_archive, output_dir):
    database, truth_csv, labels, release_archive, output = (
        Path(path).resolve() for path in (database, truth_csv, labels, release_archive, output_dir))
    if any((parent / '.git').exists() for parent in (output, *output.parents)):
        raise ValueError('Ground truth must remain outside git repositories.')
    if output.exists():
        raise FileExistsError(output)
    inputs = {path: digest(path) for path in (database, truth_csv, labels, release_archive)}
    if inputs[truth_csv] != EXPECTED_SHA256 or inputs[release_archive] != RELEASE_SHA256:
        raise ValueError('Source CSV or Release archive checksum mismatch.')
    with zipfile.ZipFile(release_archive) as archive:
        manifest = json.loads(archive.read('account-demo/manifest.json'))
        info = json.loads(archive.read('DATASET-INFO.json'))
    if (manifest['inputs']['banksim'] != EXPECTED_SHA256
            or manifest['inputs']['version'] != 'account-demo-v3'
            or manifest['label_digests']['banksim'] != inputs[labels]
            or info['database_digests']['banksim'] != inputs[database]):
        raise ValueError('Release manifest, labels or installed database mismatch.')
    dataset = 'banksim:' + EXPECTED_SHA256
    count = positives = 0
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('BEGIN')
        counts = tuple(db.execute('SELECT count(*),count(DISTINCT id),'
                                  'count(DISTINCT source_record_key) FROM transactions').fetchone())
        if counts != (EXPECTED_ROWS,) * 3:
            raise ValueError('Missing or duplicate BankSim transaction IDs/source keys.')
        rows = db.execute('SELECT t.*, f.customer_code,f.merchant_code,f.age_band,f.gender,'
                          'f.zipcode_origin,f.zipcode_merchant,o.source_dataset_id AS origin_dataset,'
                          'o.source_record_key AS origin_key,o.source_owner AS origin_owner,'
                          'a.owner AS account_owner,a.source_owner AS account_source_owner '
                          'FROM transactions t LEFT JOIN banksim_features f '
                          'ON f.owner=t.owner AND f.transaction_id=t.id '
                          'LEFT JOIN account_origins o ON o.owner=t.owner AND o.transaction_id=t.id '
                          'LEFT JOIN accounts a ON a.account_token=t.account_token '
                          'ORDER BY t.source_record_key')
        with labels.open(encoding='utf-8') as file:
            for original, label_line, stored in zip_longest(banksim_rows(truth_csv, dataset), file, rows):
                if original is None or label_line is None or stored is None:
                    raise ValueError('Incomplete source, transaction or label coverage.')
                row, fraud = original
                label = json.loads(label_line)
                account = local_token('acct_', dataset, row.owner)
                expected = {'id': row.id, 'account_token': account, 'fraud': fraud,
                            'label_origin': 'banksim-ground-truth'}
                if label != expected or type(label.get('fraud')) is not bool:
                    raise ValueError(f'Ground truth mismatch at source row {count + 1}.')
                fields = ('id', 'source', 'dataset_id', 'source_record_key', 'customer_token',
                          'amount_minor', 'currency', 'simulation_step', 'source_category')
                features = row.banksim_features.model_dump()
                if (any(stored[name] != getattr(row, name) for name in fields)
                        or any(stored[name] != value for name, value in features.items())
                        or stored['occurred_at'] is not None or stored['occurred_date'] is not None
                        or stored['account_token'] != account
                        or stored['owner'] != stored['account_owner']
                        or stored['account_source_owner'] != row.owner
                        or stored['origin_owner'] != row.owner
                        or stored['origin_dataset'] != dataset
                        or stored['origin_key'] != row.source_record_key):
                    raise ValueError(f'Transaction provenance mismatch at source row {count + 1}.')
                count += 1
                positives += fraud
    if ((count, positives) != (EXPECTED_ROWS, EXPECTED_POSITIVES)
            or manifest['report']['banksim']['transactions'] != count
            or manifest['report']['banksim']['fraud_samples'] != positives):
        raise ValueError('Unexpected BankSim record or fraud-positive count.')
    report = {'format': 'trustledger-banksim-ground-truth-v1', 'dataset_id': dataset,
              'release_tag': RELEASE_TAG, 'release_archive_sha256': RELEASE_SHA256,
              'source_csv_sha256': EXPECTED_SHA256, 'released_database_sha256': inputs[database],
              'labels_sha256': inputs[labels], 'transactions': count, 'fraud_positives': positives,
              'unique_transaction_ids': count, 'coverage': 1, 'label_origin': 'banksim-ground-truth',
              'id_mapping': "txn_ + SHA256(dataset_id + ':' + one_based_csv_row_12_digits)[:32]"}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.banksim-labels-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'sidecar'
        stage.mkdir()
        compressed = stage / 'banksim-ground-truth-v1.jsonl.gz'
        with labels.open('rb') as source, compressed.open('wb') as target:
            with gzip.GzipFile(filename='', mode='wb', fileobj=target, mtime=0) as zipped:
                shutil.copyfileobj(source, zipped)
        report['compressed_sha256'] = digest(compressed)
        if any(digest(path) != checksum for path, checksum in inputs.items()):
            raise ValueError('Inputs changed during verification.')
        (stage / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
        (stage / 'LICENSE-BANKSIM.txt').write_text(LICENSE)
        (stage / 'USAGE.txt').write_text(USAGE)
        (stage / 'SHA256SUMS').write_text(''.join(
            f'{digest(path)}  {path.name}\n' for path in sorted(stage.iterdir())))
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('database', 'truth-csv', 'labels', 'release-archive', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_sidecar(args.database, args.truth_csv, args.labels,
                                    args.release_archive, args.output_dir), indent=2))


if __name__ == '__main__':
    main()
