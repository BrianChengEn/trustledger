"""Create isolated source stores and explicitly import existing data, without network calls.

Run with backend/.venv/bin/python scripts/import_source_databases.py
    --nessie-cache /path/to/trustledger-demo.db --banksim-csv /path/to/bs140513_032310.csv

The original CSV remains offline ground truth. Only label-free records enter the
two fixed-name SQLite files. Existing application databases are never migrated.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.adapters.dataset_import import import_banksim, import_nessie_cache  # noqa: E402
from app.core.dataset_store import DatasetStore  # noqa: E402
from prepare_research_data import EXPECTED_SHA256, sha256  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'backend/data/sources')
    parser.add_argument('--nessie-cache', type=Path)
    parser.add_argument('--banksim-csv', type=Path)
    args = parser.parse_args(argv)
    # Reuse PR20's fingerprint; explicitly supplied in-repo input is read, never copied or committed.
    if args.banksim_csv and sha256(args.banksim_csv) != EXPECTED_SHA256:
        parser.error('BankSim does not match the PR20 dataset checksum.')
    report = {}
    for source in ('nessie', 'banksim'):
        store = DatasetStore(args.output_dir / (source + '.db'), source)
        filename = args.nessie_cache if source == 'nessie' else args.banksim_csv
        if filename:
            importer = import_nessie_cache if source == 'nessie' else import_banksim
            report[source] = importer(filename, store)
        else:
            report[source] = {'status': 'not-imported'}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
