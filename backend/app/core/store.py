import json
import sqlite3
import threading
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas.api import Confirmation, MemorySummary
from app.schemas.transaction import Transaction

HISTORY_SCHEMA = """CREATE TABLE IF NOT EXISTS query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('nessie','synthetic')),
    query_name TEXT NOT NULL CHECK(query_name IN ('customers.list','accounts.list',
        'accounts.get','accounts.by_customer','deposits.by_account','withdrawals.by_account')),
    requested_at TEXT NOT NULL, http_status INTEGER CHECK(http_status BETWEEN 100 AND 599),
    duration_ms INTEGER NOT NULL CHECK(duration_ms>=0),
    transport_error TEXT CHECK(transport_error IN ('timeout','connection'))
)"""


class ConflictingConfirmation(Exception):
    pass


class Store:
    """Local SQLite persistence; all operations are scoped to the server-selected demo owner."""

    def __init__(self, filename: Path):
        filename.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.filename = filename
        self.lock = threading.Lock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS privacy_cleanup (name TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS demo_transaction_sets (
                    owner TEXT PRIMARY KEY, version TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS demo_transactions (
                    owner TEXT NOT NULL REFERENCES demo_transaction_sets(owner),
                    id TEXT NOT NULL, occurred_at TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL
                        CHECK(typeof(amount_cents)='integer' AND amount_cents>=0),
                    currency TEXT NOT NULL CHECK(currency='USD'),
                    direction TEXT NOT NULL CHECK(direction IN ('debit','credit')),
                    merchant_display TEXT NOT NULL CHECK(length(merchant_display)<=80),
                    merchant_category TEXT NOT NULL CHECK(length(merchant_category)<=40),
                    source TEXT NOT NULL CHECK(source='synthetic'),
                    account_token TEXT NOT NULL,
                    is_subscription INTEGER NOT NULL CHECK(is_subscription IN (0,1)),
                    PRIMARY KEY(owner,id));
                CREATE TABLE IF NOT EXISTS confirmations (
                    owner TEXT, alert_id TEXT, decision TEXT, consent INTEGER, result TEXT,
                    PRIMARY KEY(owner, alert_id));
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY, owner TEXT, summary TEXT, created_at TEXT);
                CREATE TABLE IF NOT EXISTS resource_aliases (
                    owner TEXT NOT NULL, credential_scope TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('customer','account')),
                    remote_id TEXT NOT NULL, local_id TEXT NOT NULL,
                    PRIMARY KEY(owner,credential_scope,kind,remote_id),
                    UNIQUE(owner,credential_scope,local_id));
                CREATE TABLE IF NOT EXISTS seed_runs (
                    id INTEGER PRIMARY KEY, owner TEXT NOT NULL, dataset_sha256 TEXT NOT NULL,
                    api_base_url TEXT NOT NULL, credential_fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('active','complete','blocked')),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(owner,dataset_sha256,api_base_url,credential_fingerprint));
                CREATE TABLE IF NOT EXISTS seed_records (
                    run_id INTEGER NOT NULL REFERENCES seed_runs(id),
                    kind TEXT NOT NULL CHECK(kind IN ('customer','account','deposit','withdrawal')),
                    local_id TEXT NOT NULL CHECK(length(local_id)=24),
                    parent_kind TEXT, parent_local_id TEXT, remote_id TEXT,
                    request_fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','confirmed','failed','uncertain')),
                    safe_error TEXT, updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,kind,local_id), UNIQUE(run_id,kind,remote_id),
                    FOREIGN KEY(run_id,parent_kind,parent_local_id)
                        REFERENCES seed_records(run_id,kind,local_id),
                    CHECK(state!='confirmed' OR remote_id IS NOT NULL),
                    CHECK((kind='customer' AND parent_kind IS NULL AND parent_local_id IS NULL) OR
                          (kind='account' AND parent_kind='customer' AND parent_local_id IS NOT NULL)
                          OR (kind IN ('deposit','withdrawal') AND parent_kind='account'
                              AND parent_local_id IS NOT NULL)));
            """)
            db.execute(HISTORY_SCHEMA)
            schema = db.execute("SELECT sql FROM sqlite_master WHERE name='query_history'").fetchone()[0]
            if "response_body" in schema:
                sequence = db.execute("SELECT seq FROM sqlite_sequence WHERE name='query_history'").fetchone()
                db.execute("BEGIN IMMEDIATE")
                db.execute("ALTER TABLE query_history RENAME TO query_history_legacy")
                db.execute(HISTORY_SCHEMA)
                rows = db.execute("SELECT id,owner,source,query_name,requested_at,http_status,"
                                  "duration_ms,transport_error FROM query_history_legacy").fetchall()
                for row in rows:
                    failure = json.loads(row["transport_error"]) if row["transport_error"] else None
                    error_type = failure.get("type") if isinstance(failure, dict) else None
                    if error_type not in {None, "timeout", "connection"}:
                        error_type = "connection"
                    db.execute("INSERT INTO query_history VALUES(?,?,?,?,?,?,?,?)",
                               (*tuple(row)[:-1], error_type))
                db.execute("DROP TABLE query_history_legacy")
                if sequence:
                    updated = db.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) "
                                         "WHERE name='query_history'", (sequence[0],)).rowcount
                    if not updated:
                        db.execute("INSERT INTO sqlite_sequence VALUES('query_history',?)", (sequence[0],))
                db.execute("INSERT OR IGNORE INTO privacy_cleanup VALUES('history-metadata-v1')")
                db.commit()
            pending = db.execute("SELECT 1 FROM privacy_cleanup "
                                 "WHERE name='history-metadata-v1'").fetchone()
            if pending:
                db.execute("VACUUM")
                checkpoint = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint[0]:
                    raise sqlite3.OperationalError("History privacy migration is still locked.")
                db.execute("DELETE FROM privacy_cleanup WHERE name='history-metadata-v1'")
            db.execute("CREATE INDEX IF NOT EXISTS history_owner ON query_history(owner,id)")
        filename.chmod(0o600)

    def connect(self):
        connection = sqlite3.connect(self.filename, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    def initialize_transactions(self, owner, transactions):
        values = []
        for transaction in transactions:
            row = Transaction.model_validate(transaction.model_dump())
            cents = Decimal(str(row.amount)) * 100
            if row.source != "synthetic" or not cents.is_finite() or cents != cents.to_integral_value():
                raise ValueError("Demo transactions require synthetic data and exact cents.")
            values.append((owner, row.id, row.occurred_at.isoformat(), int(cents), row.currency,
                           row.direction, row.merchant_display, row.merchant_category, row.source,
                           row.account_token, int(row.is_subscription)))
        with self.connect() as db:
            initialized = db.execute("INSERT OR IGNORE INTO demo_transaction_sets VALUES(?,?)",
                                     (owner, "synthetic-v1")).rowcount
            if initialized:
                db.executemany("INSERT INTO demo_transactions VALUES(?,?,?,?,?,?,?,?,?,?,?)", values)

    def list_transactions(self, owner):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM demo_transactions WHERE owner=? ORDER BY id",
                              (owner,)).fetchall()
        result = []
        for stored in rows:
            row = dict(stored)
            row.pop("owner")
            row["amount"] = row.pop("amount_cents") / 100
            row["is_subscription"] = bool(row["is_subscription"])
            result.append(Transaction.model_validate(row))
        return result

    def status(self, owner: str, alert_id: str) -> str:
        with self.connect() as db:
            row = db.execute("SELECT decision FROM confirmations WHERE owner=? AND alert_id=?",
                             (owner, alert_id)).fetchone()
            return row["decision"] if row else "open"

    def confirm(self, owner, alert_id, decision, consent, sentence, request_id) -> Confirmation:
        with self.lock, self.connect() as db:
            existing = db.execute("SELECT * FROM confirmations WHERE owner=? AND alert_id=?",
                                  (owner, alert_id)).fetchone()
            if existing:
                if existing["decision"] != decision or bool(existing["consent"]) != consent:
                    raise ConflictingConfirmation()
                return Confirmation.model_validate_json(existing["result"]).model_copy(
                    update={"request_id": request_id})
            result = Confirmation(alert_id=alert_id, decision=decision, memory_id=None,
                                  memory_status="pending" if sentence else (
                                      "skipped" if consent else "not-requested"),
                                  request_id=request_id)
            db.execute("INSERT INTO confirmations VALUES (?,?,?,?,?)", (
                owner, alert_id, decision, int(consent), result.model_dump_json()))
            db.commit()
            if sentence:
                memory_id = "mem_" + uuid4().hex
                try:
                    db.execute("INSERT INTO memories VALUES (?,?,?,?)", (
                        memory_id, owner, sentence, datetime.now(timezone.utc).isoformat()))
                    result = result.model_copy(update={"memory_id": memory_id,
                                                       "memory_status": "written"})
                    db.execute("UPDATE confirmations SET result=? WHERE owner=? AND alert_id=?",
                               (result.model_dump_json(), owner, alert_id))
                    db.commit()
                except sqlite3.Error:
                    db.rollback()
                    result = result.model_copy(update={"memory_id": None, "memory_status": "failed"})
                    db.execute("UPDATE confirmations SET result=? WHERE owner=? AND alert_id=?",
                               (result.model_dump_json(), owner, alert_id))
            return result

    def list_memories(self, owner: str) -> list[MemorySummary]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM memories WHERE owner=? ORDER BY created_at DESC",
                              (owner,)).fetchall()
        return [MemorySummary(memory_id=r["memory_id"], summary=r["summary"],
                              created_at=r["created_at"], source="local-fallback") for r in rows]

    def delete_memory(self, owner, memory_id) -> bool:
        with self.lock, self.connect() as db:
            return db.execute("DELETE FROM memories WHERE owner=? AND memory_id=?",
                              (owner, memory_id)).rowcount > 0

    def append_history(self, owner, result):
        transport = result["transport_error"]
        with self.lock, self.connect() as db:
            cursor = db.execute("INSERT INTO query_history(owner,source,query_name,requested_at,"
                                "http_status,duration_ms,transport_error) VALUES(?,?,?,?,?,?,?)", (
                owner, result["source"], result["query"], result["requested_at"],
                result["http_status"], result["duration_ms"], transport["type"] if transport else None))
            return cursor.lastrowid

    @staticmethod
    def history_row(row):
        result = dict(row)
        result.pop("owner")
        result["history_id"] = result.pop("id")
        result["query"] = result.pop("query_name")
        failure = result["transport_error"]
        result["transport_error"] = ({"type": failure, "message": "Nessie request did not complete."}
                                     if failure else None)
        return result

    def list_history(self, owner, before_id=None):
        cursor_clause = " AND id < ?" if before_id is not None else ""
        args = (owner, before_id) if before_id is not None else (owner,)
        with self.connect() as db:
            rows = db.execute("SELECT * FROM query_history WHERE owner=?" + cursor_clause +
                              " ORDER BY id DESC LIMIT 51", args).fetchall()
        return {"items": [self.history_row(row) for row in rows[:50]],
                "next_cursor": rows[49]["id"] if len(rows) > 50 else None}

    def alias_resources(self, owner, scope, kind, remote_ids):
        with self.connect() as db:
            db.executemany("INSERT OR IGNORE INTO resource_aliases VALUES(?,?,?,?,?)",
                           [(owner, scope, kind, remote_id, kind + "_" + uuid4().hex)
                            for remote_id in remote_ids])
            rows = db.execute("SELECT remote_id,local_id FROM resource_aliases WHERE owner=? "
                              "AND credential_scope=? AND kind=?", (owner, scope, kind)).fetchall()
        return {row["remote_id"]: row["local_id"] for row in rows}

    def list_resources(self, owner, scope):
        with self.connect() as db:
            rows = db.execute("SELECT local_id AS resource_id,kind FROM resource_aliases "
                              "WHERE owner=? AND credential_scope=? ORDER BY local_id",
                              (owner, scope)).fetchall()
        return [dict(row) for row in rows]

    def resolve_resource(self, owner, scope, local_id):
        with self.connect() as db:
            row = db.execute("SELECT remote_id FROM resource_aliases WHERE owner=? "
                             "AND credential_scope=? AND local_id=?", (owner, scope, local_id)).fetchone()
        return row["remote_id"] if row else None

    def get_history(self, owner, history_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM query_history WHERE owner=? AND id=?",
                             (owner, history_id)).fetchone()
        return self.history_row(row) if row else None

    def delete_history(self, owner, history_id=None):
        with self.lock, self.connect() as db:
            if history_id is None:
                count = db.execute("DELETE FROM query_history WHERE owner=?", (owner,)).rowcount
            else:
                count = db.execute("DELETE FROM query_history WHERE owner=? AND id=?",
                                   (owner, history_id)).rowcount
        return count
