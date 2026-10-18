"""Isolated copy of the shared demo plus the tested txn_syn_009 duplicate.

The shared fixture and trustledger-demo.db stay unchanged. txn_syn_004 is the
existing StreamWave 11.99 alert. txn_syn_009 is the later matching charge from
the relevant-memory regression. Both are rule alerts, not fraud ground truth.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.adapters.synthetic import load_transactions
from app.core.store import Store
from app.schemas.transaction import Transaction

OWNER = "demo-user-001"
LATER_ID = "txn_syn_009"
EARLIER_ALERT_ID = "txn_syn_004"
DEMO_DATABASE_NAME = "trustledger-demo.db"
DEDICATED_DATABASE_NAME = "level2-similar-alerts.db"

LATER = Transaction(
    id=LATER_ID,
    occurred_at="2026-10-17T16:00:00-04:00",
    amount=11.99,
    currency="USD",
    direction="debit",
    merchant_display="StreamWave",
    merchant_category="streaming",
    source="synthetic",
    account_token="acct_demo_a1",
    is_subscription=True,
    kind="purchase",
)


def _stored_values(row: Transaction) -> tuple:
    cents = Decimal(str(row.amount)) * 100
    if not cents.is_finite() or cents != cents.to_integral_value():
        raise ValueError("txn_syn_009 amount must be exact cents.")
    return (
        row.id, row.occurred_at.isoformat(), int(cents), row.currency, row.direction,
        row.merchant_display, row.merchant_category, row.source, row.account_token,
        int(row.is_subscription), row.kind,
    )


def seed_level2_pair(store: Store, owner: str = OWNER) -> int:
    """Insert the baseline, then txn_syn_009. A second call does not change rows."""
    if Path(store.filename).name == DEMO_DATABASE_NAME:
        raise RuntimeError("Refusing to add txn_syn_009 to trustledger-demo.db.")
    load_transactions(store, owner)
    expected = _stored_values(LATER)
    with store.connect() as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(demo_transactions)")]
        if "kind" not in columns or len(columns) != 12:
            raise RuntimeError("demo_transactions schema is not the current 12-column table.")
        current = db.execute(
            """SELECT id,occurred_at,amount_cents,currency,direction,merchant_display,
                      merchant_category,source,account_token,is_subscription,kind
               FROM demo_transactions WHERE owner=? AND id=?""",
            (owner, LATER_ID)).fetchone()
        if current is None:
            db.execute(
                "INSERT INTO demo_transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (owner, *expected))
        elif tuple(current) != expected:
            raise RuntimeError("txn_syn_009 already exists with different values.")
        count = db.execute(
            "SELECT COUNT(*) FROM demo_transactions WHERE owner=?", (owner,)).fetchone()[0]
    return int(count)


def prepare_database(database: Path, *, reset: bool = False) -> int:
    """Seed a non-demo file. Reset deletes only the dedicated level2 filename."""
    database = database.expanduser().resolve()
    if database.name == DEMO_DATABASE_NAME:
        raise PermissionError("Refusing trustledger-demo.db.")
    if reset and database.name != DEDICATED_DATABASE_NAME:
        raise PermissionError("Reset only deletes a file named level2-similar-alerts.db.")
    if reset:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{database}{suffix}").unlink(missing_ok=True)
    return seed_level2_pair(Store(database))
