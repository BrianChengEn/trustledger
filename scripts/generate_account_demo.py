"""Build offline 100-row account histories without modifying original sources.

backend/.venv/bin/python scripts/generate_account_demo.py --banksim-csv /path/banks.csv
    --nessie-db /path/normalized/nessie.db

Restart the backend after installing the generated batch. Labels remain offline.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.adapters.account_demo import build_account_demo  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--banksim-csv', required=True, type=Path)
    parser.add_argument('--nessie-db', required=True, type=Path)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'backend/data/sources/account-demo')
    parser.add_argument('--labels-dir', type=Path, default=ROOT / 'evaluation/datasets/account-demo-labels')
    parser.add_argument('--seed', type=int, default=2026)
    args = parser.parse_args()
    report = build_account_demo(args.banksim_csv, args.nessie_db, args.output_dir, args.labels_dir, seed=args.seed)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
