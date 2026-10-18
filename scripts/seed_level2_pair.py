"""Create an isolated SQLite file with txn_syn_004 and txn_syn_009.

The shared synthetic fixture and trustledger-demo.db are not opened for writing.
Default file: backend/data/level2-similar-alerts.db. That directory is gitignored.

From the repository root:

    backend/.venv/bin/python scripts/seed_level2_pair.py

Delete only that dedicated file:

    backend/.venv/bin/python scripts/seed_level2_pair.py --reset
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.level2_pair import DEDICATED_DATABASE_NAME, prepare_database  # noqa: E402

DEFAULT_DATABASE = ROOT / "backend" / "data" / DEDICATED_DATABASE_NAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the isolated similar-alert demo.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args(argv)
    database = args.database if args.database.is_absolute() else ROOT / args.database
    try:
        count = prepare_database(database, reset=args.reset)
    except PermissionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"database {database}")
    print(f"demo-user-001 {count}")
    print("txn_syn_004 and txn_syn_009 are both present. Shared baseline was not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
