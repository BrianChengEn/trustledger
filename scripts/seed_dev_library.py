"""Seed a separate development SQLite file with the synthetic dev library.

Default database: backend/data/dev-library.db
That directory is gitignored. The command does not open trustledger-demo.db
unless --database points at it, and --reset-dev-owners refuses that file
unless --allow-demo-database is also present.

From the repository root:

    backend/.venv/bin/python scripts/seed_dev_library.py
    backend/.venv/bin/python scripts/seed_dev_library.py --reset-dev-owners

The second command deletes only owners whose ids start with dev-library-.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.dev_library import reset_dev_owners, seed  # noqa: E402
from app.core.store import Store  # noqa: E402

DEFAULT_DATABASE = ROOT / "backend" / "data" / "dev-library.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the synthetic development library.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--reset-dev-owners", action="store_true")
    parser.add_argument("--allow-demo-database", action="store_true")
    args = parser.parse_args(argv)
    database = args.database if args.database.is_absolute() else ROOT / args.database
    if database.name == "trustledger-demo.db" and args.reset_dev_owners and not args.allow_demo_database:
        print("Refusing to reset owners in trustledger-demo.db without --allow-demo-database.", file=sys.stderr)
        return 2
    store = Store(database)
    if args.reset_dev_owners:
        removed = reset_dev_owners(store)
        print(f"removed_dev_owners {len(removed)}")
    counts = seed(store)
    print(f"database {database}")
    for owner, count in sorted(counts.items()):
        print(f"{owner} {count}")
    demo = store.list_transactions("demo-user-001")
    print(f"demo-user-001 {len(demo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
