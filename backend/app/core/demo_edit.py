"""Admin editing of the synthetic demo transactions (SQLite table demo_transactions).

Every change is one all-or-nothing database transaction. Only synthetic rows can ever exist in this table (a CHECK
constraint enforces source='synthetic'), so this module cannot introduce real or live data. A charge whose alert the user
already decided is never edited or deleted: use Reset instead, which clears decisions and local memories together.
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from app.core.store import DEMO_INSERT, Store
from app.schemas.demo_admin import ROW_CAP, DemoTransactionIn, DemoTransactionPatch
from app.schemas.transaction import Transaction

ACCOUNT = "acct_demo_a1"
LOG_LIMIT = 200
SELECT = """SELECT t.id, t.occurred_at, t.amount_cents, t.merchant_display, t.merchant_category, t.direction,
    t.is_subscription, t.kind, t.origin, t.edited_at,
    EXISTS(SELECT 1 FROM confirmations c WHERE c.owner = t.owner AND c.alert_id = 'alert_' || t.id) AS decided
    FROM demo_transactions t"""


class DemoEditError(Exception):
    """Carries a safe, fixed error code and HTTP status. Never includes row data."""

    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


def _cents(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


def _row(record: sqlite3.Row) -> dict:
    return {"id": record["id"], "occurred_at": record["occurred_at"], "amount": record["amount_cents"] / 100,
            "merchant_display": record["merchant_display"], "merchant_category": record["merchant_category"],
            "direction": record["direction"], "is_subscription": bool(record["is_subscription"]), "kind": record["kind"],
            "origin": record["origin"], "edited_at": record["edited_at"], "decided": bool(record["decided"])}


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


# (merchant, category, amount in cents, minutes before now, recurring) per charge. Several merchants per scenario so
# running one twice does not pile identical charges onto the same merchant.
SCENARIOS = {
    "duplicate": [[("Corner Bistro", "dining", 2340, 12, False), ("Corner Bistro", "dining", 2340, 6, False)],
                  [("Harbor Cafe", "dining", 1875, 11, False), ("Harbor Cafe", "dining", 1875, 5, False)],
                  [("Maple Grocer", "groceries", 6420, 9, False), ("Maple Grocer", "groceries", 6420, 4, False)]],
    "large_purchase": [[("Skyline Electronics", "electronics", 129900, 3, False)],
                       [("Summit Outfitters", "other", 84950, 3, False)],
                       [("Apex Appliances", "electronics", 56000, 3, False)]],
    "price_hike": [[("StreamNest", "streaming", 999, 60 * 24 * 30, True), ("StreamNest", "streaming", 1499, 60, True)],
                   [("PulseFit", "fitness_subscription", 2999, 60 * 24 * 30, True), ("PulseFit", "fitness_subscription", 4499, 60, True)],
                   [("CloudVault", "other", 499, 60 * 24 * 30, True), ("CloudVault", "other", 899, 60, True)]],
}
SCENARIO_TITLES = {"duplicate": "duplicate charge", "large_purchase": "large purchase", "price_hike": "subscription price hike"}


class DemoEditor:
    def __init__(self, store: Store, owner: str):
        self.store, self.owner = store, owner

    # -- reads ------------------------------------------------------------------------------------------------------
    def rows(self) -> list[dict]:
        with self.store.connect() as db:
            records = db.execute(SELECT + " WHERE t.owner=? ORDER BY t.occurred_at DESC, t.id", (self.owner,)).fetchall()
        return [_row(r) for r in records]

    def log(self, limit: int = 50) -> list[dict]:
        with self.store.connect() as db:
            records = db.execute("SELECT id,at,action,tx_id,summary FROM demo_edit_log WHERE owner=? ORDER BY id DESC LIMIT ?",
                                 (self.owner, limit)).fetchall()
        return [dict(r) for r in records]

    # -- writes -----------------------------------------------------------------------------------------------------
    def _begin(self, db) -> None:
        db.execute("BEGIN IMMEDIATE")

    def _record(self, db, action: str, tx_id: str | None, summary: str) -> None:
        db.execute("INSERT INTO demo_edit_log (owner,at,action,tx_id,summary) VALUES (?,?,?,?,?)",
                   (self.owner, datetime.now(timezone.utc).isoformat(), action, tx_id, summary[:200]))
        db.execute("DELETE FROM demo_edit_log WHERE owner=? AND id NOT IN "
                   "(SELECT id FROM demo_edit_log WHERE owner=? ORDER BY id DESC LIMIT ?)", (self.owner, self.owner, LOG_LIMIT))

    def _count(self, db) -> int:
        return db.execute("SELECT COUNT(*) FROM demo_transactions WHERE owner=?", (self.owner,)).fetchone()[0]

    def _insert(self, db, *, merchant, category, cents, occurred_at: datetime, direction, subscription, when: datetime) -> str:
        tx_id = "txn_syn_adm_" + uuid4().hex[:10]
        db.execute(
            "INSERT INTO demo_transactions (owner,id,occurred_at,amount_cents,currency,direction,merchant_display,"
            "merchant_category,source,account_token,is_subscription,kind,origin,edited_at) "
            "VALUES (?,?,?,?,'USD',?,?,?,'synthetic',?,?,'purchase','admin',?)",
            (self.owner, tx_id, occurred_at.isoformat(), cents, direction, merchant, category, ACCOUNT,
             int(subscription), when.isoformat()))
        return tx_id

    def _fetch(self, db, tx_id: str) -> dict | None:
        record = db.execute(SELECT + " WHERE t.owner=? AND t.id=?", (self.owner, tx_id)).fetchone()
        return _row(record) if record else None

    def create(self, body: DemoTransactionIn) -> dict:
        now = datetime.now(timezone.utc)
        with self.store.lock, self.store.connect() as db:
            self._begin(db)
            if self._count(db) >= ROW_CAP:
                raise DemoEditError(409, "row_cap")
            tx_id = self._insert(db, merchant=body.merchant, category=body.category, cents=_cents(body.amount),
                                 occurred_at=body.occurred_at, direction=body.direction, subscription=body.is_subscription, when=now)
            self._record(db, "create", tx_id, f"Added {body.merchant} {_money(_cents(body.amount))}")
            return self._fetch(db, tx_id)

    def _editable(self, db, tx_id: str) -> dict:
        current = self._fetch(db, tx_id)
        if current is None:
            raise DemoEditError(404, "not_found")
        if current["decided"]:
            raise DemoEditError(409, "decision_exists")
        return current

    def update(self, tx_id: str, patch: DemoTransactionPatch) -> dict:
        now = datetime.now(timezone.utc)
        with self.store.lock, self.store.connect() as db:
            self._begin(db)
            current = self._editable(db, tx_id)
            fields = patch.model_dump(exclude_unset=True)
            merchant = fields.get("merchant", current["merchant_display"])
            category = fields.get("category", current["merchant_category"])
            cents = _cents(fields["amount"]) if "amount" in fields else round(current["amount"] * 100)
            occurred = fields["occurred_at"].isoformat() if "occurred_at" in fields else current["occurred_at"]
            direction = fields.get("direction", current["direction"])
            subscription = fields.get("is_subscription", current["is_subscription"])
            db.execute("UPDATE demo_transactions SET merchant_display=?,merchant_category=?,amount_cents=?,occurred_at=?,"
                       "direction=?,is_subscription=?,edited_at=? WHERE owner=? AND id=?",
                       (merchant, category, cents, occurred, direction, int(subscription), now.isoformat(), self.owner, tx_id))
            self._record(db, "update", tx_id, f"Changed {merchant} {_money(cents)}")
            return self._fetch(db, tx_id)

    def delete(self, tx_id: str) -> None:
        with self.store.lock, self.store.connect() as db:
            self._begin(db)
            current = self._editable(db, tx_id)
            db.execute("DELETE FROM demo_transactions WHERE owner=? AND id=?", (self.owner, tx_id))
            self._record(db, "delete", tx_id, f"Deleted {current['merchant_display']} {_money(round(current['amount'] * 100))}")

    def scenario(self, name: str) -> list[dict]:
        now = datetime.now(timezone.utc)
        with self.store.lock, self.store.connect() as db:
            self._begin(db)
            variants = SCENARIOS[name]
            runs = db.execute("SELECT COUNT(*) FROM demo_edit_log WHERE owner=? AND action='scenario' AND summary LIKE ?",
                              (self.owner, f"%{SCENARIO_TITLES[name]}%")).fetchone()[0]
            charges = variants[runs % len(variants)]
            if self._count(db) + len(charges) > ROW_CAP:
                raise DemoEditError(409, "row_cap")
            ids = [self._insert(db, merchant=m, category=c, cents=cents, occurred_at=now - timedelta(minutes=minutes),
                                direction="debit", subscription=recurring, when=now) for m, c, cents, minutes, recurring in charges]
            merchant, _, cents, _, _ = charges[-1]
            self._record(db, "scenario", ids[-1], f"Injected {SCENARIO_TITLES[name]}: {merchant} {_money(cents)}")
            return [self._fetch(db, i) for i in ids]

    def reset(self, baseline: list[Transaction]) -> dict:
        values = []
        for tx in baseline:
            cents = Decimal(str(tx.amount)) * 100
            if tx.source != "synthetic" or cents != cents.to_integral_value():
                raise DemoEditError(500, "baseline_invalid")
            values.append((self.owner, tx.id, tx.occurred_at.isoformat(), int(cents), tx.currency, tx.direction,
                           tx.merchant_display, tx.merchant_category, tx.source, tx.account_token, int(tx.is_subscription), tx.kind))
        with self.store.lock, self.store.connect() as db:
            self._begin(db)
            remote = db.execute("SELECT COUNT(*) FROM memories WHERE owner=? AND source='backboard'", (self.owner,)).fetchone()[0]
            remote += db.execute("SELECT COUNT(*) FROM memory_jobs WHERE owner=? AND remote_id IS NOT NULL "
                                 "AND state IN ('pending','confirmed')", (self.owner,)).fetchone()[0]
            if remote:
                # Backboard memories have their own delete path and failure handling; reset never touches them.
                raise DemoEditError(409, "remote_memory_exists")
            decisions = db.execute("SELECT COUNT(*) FROM confirmations WHERE owner=?", (self.owner,)).fetchone()[0]
            memories = db.execute("SELECT COUNT(*) FROM memories WHERE owner=?", (self.owner,)).fetchone()[0]
            # Children first: memory_job_baseline -> memory_jobs -> confirmations.
            db.execute("DELETE FROM memory_job_baseline WHERE owner=?", (self.owner,))
            db.execute("DELETE FROM memory_jobs WHERE owner=?", (self.owner,))
            db.execute("DELETE FROM memories WHERE owner=?", (self.owner,))
            db.execute("DELETE FROM confirmations WHERE owner=?", (self.owner,))
            db.execute("DELETE FROM demo_transactions WHERE owner=?", (self.owner,))
            db.executemany(DEMO_INSERT, values)
            db.execute("UPDATE demo_transaction_sets SET version='synthetic-v2' WHERE owner=?", (self.owner,))
            self._record(db, "reset", None, f"Reset to the original {len(values)} transactions")
            return {"restored": len(values), "cleared_decisions": decisions, "cleared_memories": memories}
