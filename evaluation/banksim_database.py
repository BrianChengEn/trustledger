"""Export verified SQLite inputs for the unchanged PR17 offline benchmark.

Run from the repository root with backend/.venv/bin/python -m evaluation.banksim_database
    --database backend/data/sources/banksim.db --truth-csv /path/to/banks.csv
    --output /path/outside/git/research.csv

Only this offline export joins labels. No production API imports this module.
"""
import argparse
import csv
import json
import os
import platform
import sqlite3
import tempfile
from decimal import Decimal
from itertools import zip_longest
from pathlib import Path

from scripts.prepare_research_data import EXPECTED_HEADER, EXPECTED_SHA256, ROOT, sha256


def export_database(database: Path, truth_csv: Path, output: Path):
    database, truth_csv, output = (Path(path).resolve() for path in (database, truth_csv, output))
    if any((parent / '.git').exists() for parent in output.parents):
        raise ValueError('Research labels must be exported outside git repositories.')
    digest = sha256(truth_csv)
    dataset = 'banksim:' + digest
    splits = {name: {'rows': 0, 'fraud': 0} for name in ('train', 'select', 'confirm', 'test')}
    count = labels = 0
    db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    temporary = None
    try:
        db.execute('BEGIN')
        if tuple(db.execute('SELECT source FROM source_metadata').fetchone() or ()) != ('banksim',):
            raise ValueError('Expected a BankSim source database.')
        # Original order is required: the frozen benchmark subsequently sorts (step, file order).
        rows = db.execute('SELECT t.*,f.customer_code,f.merchant_code,f.age_band,f.gender,'
                          'f.zipcode_origin,f.zipcode_merchant FROM transactions t '
                          'LEFT JOIN banksim_features f ON f.owner=t.owner AND f.transaction_id=t.id '
                          'ORDER BY CAST(t.source_record_key AS INTEGER)')
        with truth_csv.open(newline='', encoding='utf-8') as source, tempfile.NamedTemporaryFile(
                mode='w', newline='', encoding='utf-8', dir=output.parent, delete=False) as target:
            temporary = Path(target.name)
            original = csv.reader(source)
            if next(original, None) != EXPECTED_HEADER:
                raise ValueError('Unexpected BankSim header.')
            writer = csv.writer(target)
            writer.writerow(EXPECTED_HEADER)
            for number, (stored, raw) in enumerate(zip_longest(rows, original), 1):
                if stored is None or raw is None or len(raw) != len(EXPECTED_HEADER):
                    raise ValueError('Database and CSV row counts or widths differ.')
                raw = [value.strip().strip("'") for value in raw]
                if (stored['source'] != 'banksim' or stored['dataset_id'] != dataset
                        or stored['source_record_key'] != f'{number:012d}'
                        or stored['currency'] != 'EUR' or stored['occurred_at'] is not None
                        or stored['occurred_date'] is not None or raw[9] not in {'0', '1'}):
                    raise ValueError(f'BankSim provenance or semantics mismatch at row {number}.')
                amount = Decimal(stored['amount_minor']) / 100
                restored = [str(stored['simulation_step']), stored['customer_code'],
                            stored['age_band'] or '', stored['gender'] or '',
                            stored['zipcode_origin'] or '', stored['merchant_code'],
                            stored['zipcode_merchant'] or '', stored['source_category'],
                            format(amount, '.2f'), raw[9]]
                if restored[:8] != raw[:8] or amount != Decimal(raw[8]):
                    raise ValueError(f'BankSim data mismatch at row {number}.')
                writer.writerow(restored)
                step, label = stored['simulation_step'], int(raw[9])
                if not 0 <= step <= 179:
                    raise ValueError('BankSim step is outside the frozen benchmark.')
                split = 'train' if step <= 119 else 'select' if step <= 134 else 'confirm' if step <= 149 else 'test'
                splits[split]['rows'] += 1
                splits[split]['fraud'] += label
                count += 1
                labels += label
        if sha256(truth_csv) != digest:
            raise ValueError('Source CSV changed during verification.')
        references = ['evaluation/research/benchmark/contract.py',
                      'evaluation/research/v2/run_framework.py',
                      'evaluation/research/benchmark/trustledger/scores/v2_merchant_step_causal.json',
                      'evaluation/banksim_database.py', 'data/manifests/banksim.yaml']
        report = {'dataset_id': dataset, 'transactions': count, 'fraud_labels': labels,
                  'currency': 'EUR', 'simulation_step_unit': 'day', 'splits': splits,
                  'export_sha256': sha256(temporary), 'export_python': platform.python_version(),
                  'benchmark_rerun': 'not-run',
                  'reference_sha256': {name: sha256(ROOT / name) for name in references}}
        # Publish only a complete, verified file; never replace an existing research artifact.
        os.link(temporary, output)
        return report
    finally:
        db.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--truth-csv', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sha256(args.truth_csv) != EXPECTED_SHA256:
        parser.error('BankSim does not match the PR20 dataset checksum.')
    print(json.dumps(export_database(args.database, args.truth_csv, args.output), indent=2))


if __name__ == '__main__':
    main()
