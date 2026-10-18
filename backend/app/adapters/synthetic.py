from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.store import Store
from app.schemas.transaction import Transaction

BASELINE = (
    ("001", "2026-10-16T09:15:00-04:00", 6.45, "Campus Coffee", "dining", False),
    ("002", "2026-10-16T18:32:00-04:00", 42.18, "Fresh Basket", "groceries", False),
    ("003", "2026-10-17T13:57:00-04:00", 11.99, "StreamWave", "streaming", True),
    ("004", "2026-10-17T14:03:00-04:00", 11.99, "StreamWave", "streaming", True),
    ("005", "2026-10-17T15:10:00-04:00", 849.0, "Tech Harbor", "electronics", False),
    ("006", "2026-10-15T20:44:00-04:00", 18.5, "Metro Ride", "transportation", False),
    ("007", "2026-09-17T08:00:00-04:00", 24.99, "FitFlow", "fitness_subscription", True),
    ("008", "2026-10-17T08:00:00-04:00", 34.99, "FitFlow", "fitness_subscription", True),
)


def load_transactions(store: Store | None = None, owner="demo-user-001") -> list[Transaction]:
    if store is None:
        with TemporaryDirectory(prefix="trustledger-synthetic-") as directory:
            return load_transactions(Store(Path(directory) / "demo.db"), owner)
    rows = [Transaction(id="txn_syn_" + number, occurred_at=occurred_at, amount=amount,
                        currency="USD", direction="debit", merchant_display=merchant,
                        merchant_category=category, source="synthetic", account_token="acct_demo_a1",
                        is_subscription=subscription)
            for number, occurred_at, amount, merchant, category, subscription in BASELINE]
    store.initialize_transactions(owner, rows)
    return store.list_transactions(owner)
