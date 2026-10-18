"""Seed only the dedicated Level 2 database; never import app.main here.

Run with backend/.venv/bin/python scripts/seed_level2_pair.py.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

DATABASE = ROOT / 'backend/data/level2-similar-alerts.db'
OWNER = 'demo-user-001'
COLUMNS = ('owner,id,occurred_at,amount_cents,currency,direction,merchant_display,'
           'merchant_category,source,account_token,is_subscription,kind')
VALUES = (OWNER, 'txn_syn_009', '2026-10-17T16:00:00-04:00', 1199, 'USD', 'debit',
          'StreamWave', 'streaming', 'synthetic', 'acct_demo_a1', 1, 'purchase')


def prepare_database(path: Path = DATABASE) -> int:
    # Validate before Store can initialize or migrate anything. No reset/delete option.
    path = path.expanduser().absolute()
    if path.name != DATABASE.name or path.is_symlink():
        raise ValueError('Use a dedicated, non-symlink level2-similar-alerts.db file')
    if path.exists() and path.stat().st_nlink != 1:
        raise ValueError('Hard-linked databases are forbidden')
    path = path.resolve()
    protected = ROOT / 'backend/data/trustledger-demo.db'
    if path == protected.resolve() or (path.exists() and protected.exists()
                                      and path.samefile(protected)):
        raise ValueError('The shared demo database is forbidden')
    from app.adapters.synthetic import load_transactions
    from app.core.store import Store

    store = Store(path)
    load_transactions(store, OWNER)
    with store.connect() as db:
        current = db.execute(f'SELECT {COLUMNS} FROM demo_transactions WHERE owner=? AND id=?',
                             (OWNER, VALUES[1])).fetchone()
        if current is None:
            db.execute(f'INSERT INTO demo_transactions ({COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       VALUES)
        elif tuple(current) != VALUES:
            raise ValueError('txn_syn_009 already exists with different values; refusing overwrite')
        return db.execute('SELECT COUNT(*) FROM demo_transactions WHERE owner=?',
                          (OWNER,)).fetchone()[0]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=DATABASE)
    args = parser.parse_args()
    count = prepare_database(args.database)
    print(f'DATABASE_PATH={args.database.expanduser().resolve()} transactions={count}')
