import json
import sqlite3
import threading
from contextlib import contextmanager
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas.api import Confirmation, ConfirmationRequest, MemorySummary
from app.schemas.transaction import Transaction

HISTORY_SCHEMA = """CREATE TABLE IF NOT EXISTS query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('nessie','synthetic')),
    query_name TEXT NOT NULL CHECK(query_name IN ('customers.list','accounts.list',
        'accounts.get','accounts.by_customer','deposits.by_account','withdrawals.by_account',
        'purchases.by_account','transfers.by_account')),
    requested_at TEXT NOT NULL, http_status INTEGER CHECK(http_status BETWEEN 100 AND 599),
    duration_ms INTEGER NOT NULL CHECK(duration_ms>=0),
    transport_error TEXT CHECK(transport_error IN ('timeout','connection'))
)"""


DEMO_COLUMNS = ("owner,id,occurred_at,amount_cents,currency,direction,merchant_display,merchant_category,"
                "source,account_token,is_subscription,kind")
DEMO_INSERT = f"INSERT INTO demo_transactions ({DEMO_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"


class ConflictingConfirmation(Exception):
    pass


class Store:
    """Local SQLite persistence; all operations are scoped to the server-selected demo owner."""

    def __init__(self, filename: Path):
        filename.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.filename = filename
        self._backup_before_demo_edit()
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
                CREATE TABLE IF NOT EXISTS workspace_accounts (
                    owner TEXT NOT NULL, account_token TEXT NOT NULL,
                    type TEXT NOT NULL CHECK(type IN ('Checking','Savings','Credit Card')),
                    balance_cents INTEGER NOT NULL CHECK(typeof(balance_cents)='integer'),
                    rewards INTEGER NOT NULL CHECK(typeof(rewards)='integer' AND rewards>=0),
                    PRIMARY KEY(owner,account_token));
                CREATE TABLE IF NOT EXISTS workspace_movements (
                    owner TEXT NOT NULL, id TEXT NOT NULL, account_token TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('purchase','transfer','deposit','withdrawal')),
                    occurred_at TEXT NOT NULL, date_only INTEGER NOT NULL CHECK(date_only IN (0,1)),
                    amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents>=0),
                    direction TEXT NOT NULL CHECK(direction IN ('debit','credit','unknown')),
                    settlement_status TEXT NOT NULL CHECK(settlement_status IN ('pending','completed','cancelled')),
                    PRIMARY KEY(owner,id), FOREIGN KEY(owner,account_token)
                        REFERENCES workspace_accounts(owner,account_token) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS workspace_sync (
                    owner TEXT NOT NULL, account_token TEXT NOT NULL, kind TEXT NOT NULL
                        CHECK(kind IN ('accounts','purchases','transfers','deposits','withdrawals')),
                    requested_at TEXT NOT NULL, synced_at TEXT, http_status INTEGER,
                    error TEXT CHECK(error IN ('upstream','timeout','connection','schema')),
                    PRIMARY KEY(owner,account_token,kind));
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY, owner TEXT, summary TEXT, created_at TEXT,
                    source TEXT NOT NULL DEFAULT 'local-fallback', assistant_id TEXT);
                CREATE TABLE IF NOT EXISTS assistants (
                    owner TEXT PRIMARY KEY, assistant_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS memory_jobs (
                    owner TEXT, alert_id TEXT, assistant_id TEXT NOT NULL, sentence TEXT NOT NULL,
                    local_id TEXT NOT NULL, state TEXT NOT NULL
                        CHECK(state IN ('preparing','pending','confirmed','failed','deleted')), remote_id TEXT,
                    PRIMARY KEY(owner,alert_id),
                    FOREIGN KEY(owner,alert_id) REFERENCES confirmations(owner,alert_id));
                CREATE TABLE IF NOT EXISTS memory_job_baseline (
                    owner TEXT, alert_id TEXT, remote_id TEXT,
                    PRIMARY KEY(owner,alert_id,remote_id),
                    FOREIGN KEY(owner,alert_id) REFERENCES memory_jobs(owner,alert_id));
                CREATE UNIQUE INDEX IF NOT EXISTS active_memory_sentence
                    ON memory_jobs(owner,assistant_id,sentence) WHERE state IN ('preparing','pending');
                CREATE UNIQUE INDEX IF NOT EXISTS remote_memory_identity
                    ON memory_jobs(assistant_id,remote_id) WHERE remote_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS resource_aliases (
                    owner TEXT NOT NULL, credential_scope TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('customer','account')),
                    remote_id TEXT NOT NULL, local_id TEXT NOT NULL,
                    PRIMARY KEY(owner,credential_scope,kind,remote_id),
                    UNIQUE(owner,credential_scope,local_id));
                CREATE TABLE IF NOT EXISTS admin_query_rows (
                    owner TEXT NOT NULL, credential_scope TEXT NOT NULL, query_name TEXT NOT NULL,
                    resource_code TEXT NOT NULL, position INTEGER NOT NULL,
                    resource_id TEXT, account_type TEXT, balance_cents INTEGER, rewards INTEGER,
                    amount_cents INTEGER, medium TEXT, settlement_status TEXT,
                    PRIMARY KEY(owner,credential_scope,query_name,resource_code,position));
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
            alias_columns = {row[1] for row in db.execute('PRAGMA table_info(resource_aliases)')}
            if 'display_id' not in alias_columns:
                db.execute('ALTER TABLE resource_aliases ADD COLUMN display_id TEXT')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS resource_display_code ON '
                       'resource_aliases(owner,credential_scope,display_id) WHERE display_id IS NOT NULL')
            demo_columns = {row[1] for row in db.execute('PRAGMA table_info(demo_transactions)')}
            if 'kind' not in demo_columns:
                db.execute("ALTER TABLE demo_transactions ADD COLUMN kind TEXT NOT NULL DEFAULT 'purchase' "
                           "CHECK(kind IN ('purchase','transfer','deposit','withdrawal'))")
            if 'origin' not in demo_columns:
                db.execute("ALTER TABLE demo_transactions ADD COLUMN origin TEXT NOT NULL DEFAULT 'baseline' "
                           "CHECK(origin IN ('baseline','admin'))")
            if 'edited_at' not in demo_columns:
                db.execute("ALTER TABLE demo_transactions ADD COLUMN edited_at TEXT")
            db.execute("""CREATE TABLE IF NOT EXISTS demo_edit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, at TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('create','update','delete','scenario','reset')),
                tx_id TEXT, summary TEXT NOT NULL CHECK(length(summary) <= 200))""")
            movement_schema = db.execute("SELECT sql FROM sqlite_master "
                                         "WHERE name='workspace_movements'").fetchone()[0]
            if "'unknown'" not in movement_schema:
                db.execute("BEGIN IMMEDIATE")
                db.execute("ALTER TABLE workspace_movements RENAME TO workspace_movements_legacy")
                db.execute(movement_schema.replace("('debit','credit')", "('debit','credit','unknown')"))
                db.execute("INSERT INTO workspace_movements SELECT * FROM workspace_movements_legacy")
                db.execute("DROP TABLE workspace_movements_legacy")
                db.commit()
            columns = {row[1] for row in db.execute("PRAGMA table_info(memories)")}
            if "source" not in columns:
                db.execute("ALTER TABLE memories ADD COLUMN source TEXT NOT NULL DEFAULT 'local-fallback'")
            if "assistant_id" not in columns:
                db.execute("ALTER TABLE memories ADD COLUMN assistant_id TEXT")
            if "local_persisted" not in columns:
                db.execute("ALTER TABLE memories ADD COLUMN local_persisted INTEGER NOT NULL DEFAULT 0")
                # Legacy receipts prove only completed writes, never pending preparation.
                db.execute("""UPDATE memories SET local_persisted=1 WHERE EXISTS (
                    SELECT 1 FROM confirmations c WHERE c.owner=memories.owner
                    AND c.decision='normal' AND c.consent=1 AND json_valid(c.result)
                    AND json_extract(c.result,'$.memory_id')=memories.memory_id
                    AND json_extract(c.result,'$.memory_status')='written')""")
                db.commit()
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
            schema = db.execute("SELECT sql FROM sqlite_master WHERE name='query_history'").fetchone()[0]
            if "purchases.by_account" not in schema:
                db.commit()
                db.execute("BEGIN IMMEDIATE")
                sequence = db.execute("SELECT seq FROM sqlite_sequence WHERE name='query_history'").fetchone()
                db.execute("ALTER TABLE query_history RENAME TO query_history_legacy")
                db.execute(HISTORY_SCHEMA)
                db.execute("INSERT INTO query_history SELECT * FROM query_history_legacy")
                db.execute("DROP TABLE query_history_legacy")
                if sequence:
                    updated = db.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) "
                                         "WHERE name='query_history'", (sequence[0],)).rowcount
                    if not updated:
                        db.execute("INSERT INTO sqlite_sequence VALUES('query_history',?)", (sequence[0],))
            db.execute("CREATE INDEX IF NOT EXISTS history_owner ON query_history(owner,id)")
        filename.chmod(0o600)

    def _backup_before_demo_edit(self) -> None:
        """Before the first admin-edit migration, keep one untouched copy of an existing database that has data."""
        if not self.filename.exists():
            return
        backup = self.filename.with_name(self.filename.stem + '.pre-demo-edit.bak')
        try:
            with sqlite3.connect(self.filename) as source:
                columns = {row[1] for row in source.execute('PRAGMA table_info(demo_transactions)')}
                has_rows = bool(columns) and source.execute('SELECT COUNT(*) FROM demo_transactions').fetchone()[0] > 0
                if not has_rows or 'origin' in columns or backup.exists():
                    return
                with sqlite3.connect(backup) as target:
                    source.backup(target)
            backup.chmod(0o600)
        except sqlite3.DatabaseError:
            pass  # An unreadable file is left for the normal startup path to report.

    @contextmanager
    def connect(self, *, timeout: float = 5):
        connection = sqlite3.connect(self.filename, timeout=timeout)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA secure_delete=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize_transactions(self, owner, transactions):
        values = []
        for transaction in transactions:
            row = Transaction.model_validate(transaction.model_dump())
            cents = Decimal(str(row.amount)) * 100
            if row.source != "synthetic" or not cents.is_finite() or cents != cents.to_integral_value():
                raise ValueError("Demo transactions require synthetic data and exact cents.")
            values.append((owner, row.id, row.occurred_at.isoformat(), int(cents), row.currency,
                           row.direction, row.merchant_display, row.merchant_category, row.source,
                           row.account_token, int(row.is_subscription), row.kind))
        with self.connect() as db:
            initialized = db.execute("INSERT OR IGNORE INTO demo_transaction_sets VALUES(?,?)",
                                     (owner, "synthetic-v2")).rowcount
            if initialized:
                db.executemany(DEMO_INSERT, values)
            elif db.execute('SELECT version FROM demo_transaction_sets WHERE owner=?',
                            (owner,)).fetchone()[0] == 'synthetic-v1':
                existing = db.execute('SELECT id,account_token,kind FROM demo_transactions WHERE owner=?',
                                      (owner,)).fetchall()
                for account in {row['account_token'] for row in existing}:
                    missing = max(0, 10 - sum(row['account_token'] == account and row['kind'] == 'transfer'
                                              for row in existing))
                    ids = {row['id'] for row in existing}
                    additions = [row for row in values if row[9] == account and row[11] == 'transfer'
                                 and row[1] not in ids][:missing]
                    db.executemany(DEMO_INSERT, additions)
                db.execute("UPDATE demo_transaction_sets SET version='synthetic-v2' WHERE owner=?", (owner,))

    def list_transactions(self, owner):
        with self.connect() as db:
            rows = db.execute(f"SELECT {DEMO_COLUMNS} FROM demo_transactions WHERE owner=? ORDER BY id",
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

    def confirm(self, owner, alert_id, decision, consent, sentence, request_id,
                *, memory_enabled: bool = True) -> Confirmation:
        # Keep the persistence boundary strict as well as the HTTP boundary.
        ConfirmationRequest(decision=decision, consent_to_memory=consent)
        permitted = decision == "normal" and consent is True and memory_enabled is True
        write_memory = permitted and bool(sentence)
        with self.lock:
            # BEGIN IMMEDIATE serializes the read/insert across separate Store
            # instances too. Only the creator may attempt this optional write.
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute("SELECT * FROM confirmations WHERE owner=? AND alert_id=?",
                                      (owner, alert_id)).fetchone()
                if existing:
                    if existing["decision"] != decision or bool(existing["consent"]) != consent:
                        raise ConflictingConfirmation()
                    return Confirmation.model_validate_json(existing["result"]).model_copy(
                        update={"request_id": request_id})
                result = Confirmation(
                    alert_id=alert_id, decision=decision, request_id=request_id,
                    memory_status="pending" if write_memory else (
                        "skipped" if consent else "not-requested"),
                )
                db.execute("INSERT INTO confirmations VALUES (?,?,?,?,?)", (
                    owner, alert_id, decision, int(consent), result.model_dump_json()))
            # The authoritative confirmation is now committed and visible to other
            # connections. Optional work can never roll it back.
            if not write_memory:
                return result
            return self.complete_local_memory(owner, sentence, result)

    def complete_local_memory(self, owner, sentence, result):
        try:
            return self._write_memory(owner, sentence, result)
        except Exception:
            # Do not expose SQL/summary/exception text. Insert + outcome update
            # roll back together, leaving the original confirmation intact.
            failed = result.model_copy(update={"memory_status": "failed"})
            try:
                with self.connect() as db:
                    db.execute("UPDATE confirmations SET result=? WHERE owner=? AND alert_id=?",
                               (failed.model_dump_json(), owner, result.alert_id))
            except Exception:
                # If even status persistence is unavailable, return the durable
                # pending state. Replays never retry/backfill optional memory.
                return result
            return failed

    def _write_memory(self, owner: str, sentence: str, result: Confirmation) -> Confirmation:
        memory = MemorySummary(memory_id="mem_" + uuid4().hex, summary=sentence,
                               created_at=datetime.now(timezone.utc), source="local-fallback")
        written = result.model_copy(update={"memory_status": "written", "memory_id": memory.memory_id})
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO memories (memory_id,owner,summary,created_at,local_persisted) VALUES (?,?,?,?,1)", (
                memory.memory_id, owner, memory.summary, memory.created_at.isoformat()))
            db.execute("UPDATE confirmations SET result=? WHERE owner=? AND alert_id=?",
                       (written.model_dump_json(), owner, result.alert_id))
        return written

    def save_workspace_collection(self, owner, account_token, kind, rows, requested_at,
                                  http_status, error):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT requested_at FROM workspace_sync WHERE owner=? AND account_token=? AND kind=?',
                                  (owner, account_token, kind)).fetchone()
            if previous and previous['requested_at'] > requested_at:
                return
            if kind != 'accounts' and not db.execute(
                    'SELECT 1 FROM workspace_accounts WHERE owner=? AND account_token=?',
                    (owner, account_token)).fetchone():
                return
            if rows is not None:
                if kind == 'accounts':
                    db.executemany('INSERT INTO workspace_accounts VALUES(?,?,?,?,?) '
                                   'ON CONFLICT(owner,account_token) DO UPDATE SET type=excluded.type,'
                                   'balance_cents=excluded.balance_cents,rewards=excluded.rewards',
                                   [(owner, *row) for row in rows])
                    tokens = [row[0] for row in rows]
                    clause = ' AND account_token NOT IN (' + ','.join('?' for _ in tokens) + ')' if tokens else ''
                    db.execute('DELETE FROM workspace_accounts WHERE owner=?' + clause, (owner, *tokens))
                    db.execute("DELETE FROM workspace_sync WHERE owner=? AND account_token<>''" + clause,
                               (owner, *tokens))
                else:
                    db.execute('DELETE FROM workspace_movements WHERE owner=? AND account_token=? AND kind=?',
                               (owner, account_token, kind[:-1]))
                    db.executemany('INSERT INTO workspace_movements VALUES(?,?,?,?,?,?,?,?,?)',
                                   [(owner, *row) for row in rows])
            db.execute('INSERT INTO workspace_sync VALUES(?,?,?,?,?,?,?) '
                       'ON CONFLICT(owner,account_token,kind) DO UPDATE SET '
                       'requested_at=excluded.requested_at,http_status=excluded.http_status,error=excluded.error,'
                       'synced_at=COALESCE(excluded.synced_at,workspace_sync.synced_at)',
                       (owner, account_token, kind, requested_at, requested_at if error is None else None,
                        http_status, error))

    def workspace_rows(self, owner):
        with self.connect() as db:
            db.execute('BEGIN')
            return tuple([dict(row) for row in db.execute(
                f'SELECT * FROM {table} WHERE owner=? ORDER BY {order}', (owner,))]
                for table, order in [('workspace_accounts', 'account_token'),
                                     ('workspace_movements', 'occurred_at DESC,id'),
                                     ('workspace_sync', 'account_token,kind')])

    def claim_confirmation(self, owner, alert_id, decision, consent, wants_memory, request_id):
        ConfirmationRequest(decision=decision, consent_to_memory=consent)
        wants_memory = wants_memory and decision == "normal" and consent is True
        result = Confirmation(alert_id=alert_id, decision=decision, memory_id=None,
                              memory_status="pending" if wants_memory else (
                                  "skipped" if consent else "not-requested"), request_id=request_id)
        with self.lock, self.connect() as db:
            created = db.execute("INSERT OR IGNORE INTO confirmations VALUES(?,?,?,?,?)",
                                 (owner, alert_id, decision, int(consent), result.model_dump_json())).rowcount
            existing = db.execute("SELECT * FROM confirmations WHERE owner=? AND alert_id=?",
                                  (owner, alert_id)).fetchone()
            if existing["decision"] != decision or bool(existing["consent"]) != consent:
                raise ConflictingConfirmation()
            result = Confirmation.model_validate_json(existing["result"]).model_copy(
                update={"request_id": request_id})
        return result, bool(created)

    def replay_confirmation(self, owner, alert_id, decision, consent, request_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM confirmations WHERE owner=? AND alert_id=?",
                             (owner, alert_id)).fetchone()
        if row is None:
            return None
        if row["decision"] != decision or bool(row["consent"]) != consent:
            raise ConflictingConfirmation()
        return Confirmation.model_validate_json(row["result"]).model_copy(update={"request_id": request_id})

    def finish_memory(self, owner, result, sentence, *, memory_id=None, source="local-fallback",
                      assistant_id=None, memory_status=None):
        if source not in {"backboard", "local-fallback"}:
            raise ValueError("Invalid memory source.")
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT * FROM memory_jobs WHERE owner=? AND alert_id=?",
                             (owner, result.alert_id)).fetchone()
            if job and job["state"] == "deleted":
                result = result.model_copy(update={"memory_id": None, "memory_status": "skipped"})
                db.execute("UPDATE confirmations SET result=? WHERE owner=? AND alert_id=?",
                           (result.model_dump_json(), owner, result.alert_id))
                return result
            saved_id = memory_id or (job["local_id"] if job else "mem_" + uuid4().hex)
            status = memory_status or ("written" if sentence else result.memory_status)
            try:
                if sentence:
                    if job and job["local_id"] != saved_id:
                        db.execute("DELETE FROM memories WHERE owner=? AND memory_id=?",
                                   (owner, job["local_id"]))
                    db.execute("INSERT OR IGNORE INTO memories "
                               "(memory_id,owner,summary,created_at,source,assistant_id) VALUES(?,?,?,?,?,?)",
                               (saved_id, owner, sentence, datetime.now(timezone.utc).isoformat(), source, assistant_id))
                    row = db.execute("SELECT owner,summary FROM memories WHERE memory_id=?", (saved_id,)).fetchone()
                    if row["owner"] != owner or row["summary"] != sentence:
                        raise sqlite3.IntegrityError("Memory identity differs.")
                    db.execute("UPDATE memories SET source=?,assistant_id=?,local_persisted=1 WHERE owner=? AND memory_id=?",
                               (source, assistant_id, owner, saved_id))
                    if job:
                        db.execute("UPDATE memory_jobs SET remote_id=?,state=? "
                                   "WHERE owner=? AND alert_id=?", (
                                   memory_id if source == "backboard" else job["remote_id"],
                                   "confirmed" if source == "backboard" else job["state"], owner, result.alert_id))
                result = result.model_copy(update={"memory_id": saved_id if sentence else None,
                                                   "memory_status": status})
                db.execute("UPDATE confirmations SET result=? WHERE owner=? AND alert_id=?",
                           (result.model_dump_json(), owner, result.alert_id))
            except sqlite3.Error:
                db.rollback()
                result = result.model_copy(update={"memory_id": job["local_id"] if job else None,
                                                   "memory_status": "pending" if job else "failed"})
                try:
                    db.execute("UPDATE confirmations SET result=? WHERE owner=? AND alert_id=?",
                               (result.model_dump_json(), owner, result.alert_id))
                except sqlite3.Error:
                    db.rollback()
                    return self.replay_confirmation(owner, result.alert_id, result.decision, True, result.request_id)
        return result

    def prepare_memory_job(self, owner, alert_id, assistant_id, sentence):
        local_id = "mem_" + uuid4().hex
        with self.lock, self.connect() as db:
            confirmation = db.execute("SELECT * FROM confirmations WHERE owner=? AND alert_id=?",
                                      (owner, alert_id)).fetchone()
            if not confirmation or confirmation["decision"] != "normal" or not confirmation["consent"]:
                raise ValueError("A committed consented confirmation is required.")
            db.execute("INSERT INTO memories (memory_id,owner,summary,created_at,source,assistant_id) "
                       "VALUES(?,?,?,?,'local-fallback',?)",
                       (local_id, owner, sentence, datetime.now(timezone.utc).isoformat(), assistant_id))
            db.execute("INSERT INTO memory_jobs VALUES(?,?,?,?,?,'preparing',NULL)",
                       (owner, alert_id, assistant_id, sentence, local_id))
            receipt = Confirmation.model_validate_json(confirmation["result"]).model_copy(
                update={"memory_id": local_id, "memory_status": "pending"})
            db.execute("UPDATE confirmations SET result=? WHERE owner=? AND alert_id=?",
                       (receipt.model_dump_json(), owner, alert_id))
        return local_id

    def record_memory_baseline(self, owner, alert_id, before_ids):
        with self.connect() as db:
            changed = db.execute("UPDATE memory_jobs SET state='pending' "
                                 "WHERE owner=? AND alert_id=? AND state='preparing'",
                                 (owner, alert_id)).rowcount
            if changed:
                db.executemany("INSERT INTO memory_job_baseline VALUES(?,?,?)",
                               [(owner, alert_id, value) for value in before_ids])
        return bool(changed)

    def memory_job(self, owner, *, alert_id=None, memory_id=None):
        clause, values = (("alert_id=?", (alert_id,)) if alert_id is not None else
                          ("(local_id=? OR remote_id=?)", (memory_id, memory_id)))
        with self.connect() as db:
            row = db.execute("SELECT * FROM memory_jobs WHERE owner=? AND " + clause,
                             (owner, *values)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["before_ids"] = {entry[0] for entry in db.execute(
                "SELECT remote_id FROM memory_job_baseline WHERE owner=? AND alert_id=?",
                (owner, row["alert_id"]))}
        return result

    def update_memory_job(self, owner, alert_id, state, remote_id=None):
        with self.connect() as db:
            changed = db.execute("UPDATE memory_jobs SET state=?,remote_id=? "
                                 "WHERE owner=? AND alert_id=? AND state!='deleted'",
                                 (state, remote_id, owner, alert_id)).rowcount
        return bool(changed)

    def assistant_id(self, owner: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT assistant_id FROM assistants WHERE owner=?",
                             (owner,)).fetchone()
        return row["assistant_id"] if row else None

    def save_assistant(self, owner: str, assistant_id: str) -> str:
        """Keep the first assistant created for this owner. A later id is not swapped in."""
        with self.lock, self.connect() as db:
            existing = db.execute("SELECT assistant_id FROM assistants WHERE owner=?",
                                  (owner,)).fetchone()
            if existing:
                return existing["assistant_id"]
            db.execute("INSERT INTO assistants (owner, assistant_id) VALUES (?,?)",
                       (owner, assistant_id))
        return assistant_id

    def memory_row(self, owner: str, memory_id: str):
        with self.connect() as db:
            return db.execute(
                """SELECT memory_id, source, assistant_id, summary FROM memories
                   WHERE owner=? AND memory_id=?""",
                (owner, memory_id)).fetchone()

    def list_memories(self, owner: str) -> list[MemorySummary]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM memories WHERE owner=? ORDER BY created_at DESC",
                              (owner,)).fetchall()
        listed = []
        for row in rows:
            source = row["source"] if row["source"] in {"backboard", "local-fallback"} else "local-fallback"
            listed.append(MemorySummary(memory_id=row["memory_id"], summary=row["summary"],
                                        created_at=row["created_at"], source=source))
        return listed

    def consented_memory_summaries(self, owner: str, *, timeout: float = 0.1) -> list[str]:
        """Only extant memories linked to this owner's successful consented write."""
        # Optional context must not consume the frontend deadline on lock contention.
        with self.connect(timeout=timeout) as db:
            rows = db.execute("""
                SELECT m.summary FROM confirmations c JOIN memories m
                  ON m.owner = c.owner AND m.memory_id = json_extract(
                    CASE WHEN json_valid(c.result) THEN c.result ELSE '{}' END, '$.memory_id')
                WHERE c.owner = ? AND c.decision = 'normal' AND c.consent = 1
                  AND m.local_persisted = 1
            """, (owner,)).fetchall()
        return [row["summary"] for row in rows]

    def delete_memory(self, owner, memory_id) -> bool:
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT local_id,remote_id FROM memory_jobs WHERE owner=? "
                             "AND (local_id=? OR remote_id=?)", (owner, memory_id, memory_id)).fetchone()
            ids = (job["local_id"], job["remote_id"]) if job else (memory_id, memory_id)
            return db.execute("DELETE FROM memories WHERE owner=? AND memory_id IN (?,?)",
                              (owner, *ids)).rowcount > 0

    def cache_query_rows(self, owner, scope, query, resource_code, body):
        fields = ('resource_id', 'type', 'balance', 'rewards', 'amount', 'medium', 'status')
        rows = [body] if isinstance(body, dict) else body
        values = []
        for index, row in enumerate(rows):
            projected = []
            for field in fields:
                value = row.get(field)
                if value is not None and field in {'amount', 'balance'}:
                    value = Decimal(str(value)) * 100
                    if value != value.to_integral_value() or abs(value) > 9007199254740991:
                        raise ValueError('Invalid query cents')
                    value = int(value)
                projected.append(value)
            values.append((owner, scope, query, resource_code or '', index, *projected))
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            key = (owner, scope, query, resource_code or '')
            db.execute('DELETE FROM admin_query_rows WHERE owner=? AND credential_scope=? '
                       'AND query_name=? AND resource_code=?', key)
            db.executemany('INSERT INTO admin_query_rows VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', values)
            stored = db.execute('SELECT resource_id,account_type,balance_cents,rewards,amount_cents,'
                                'medium,settlement_status FROM admin_query_rows WHERE owner=? '
                                'AND credential_scope=? AND query_name=? AND resource_code=? '
                                'ORDER BY position', key).fetchall()
        result = [{field: value / 100 if field in {'amount', 'balance'} else value
                   for field, value in zip(fields, row) if value is not None} for row in stored]
        return result[0] if isinstance(body, dict) else result

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
            db.executemany("INSERT OR IGNORE INTO resource_aliases "
                           "(owner,credential_scope,kind,remote_id,local_id) VALUES(?,?,?,?,?)",
                           [(owner, scope, kind, remote_id, kind + "_" + uuid4().hex)
                            for remote_id in remote_ids])
            rows = db.execute("SELECT remote_id,COALESCE(display_id,local_id) AS local_id "
                              "FROM resource_aliases WHERE owner=? "
                              "AND credential_scope=? AND kind=?", (owner, scope, kind)).fetchall()
        return {row["remote_id"]: row["local_id"] for row in rows}

    def bind_account_codes(self, owner, scope, codes):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for remote, code in codes.items():
                existing = db.execute("SELECT display_id FROM resource_aliases WHERE owner=? "
                                      "AND credential_scope=? AND kind='account' AND remote_id=?",
                                      (owner, scope, remote)).fetchone()
                if existing is None or existing['display_id'] not in {None, code}:
                    raise ValueError('Account membership changed; reconcile the existing mapping.')
                db.execute("UPDATE resource_aliases SET display_id=? WHERE owner=? "
                           "AND credential_scope=? AND kind='account' AND remote_id=?",
                           (code, owner, scope, remote))

    def list_resources(self, owner, scope):
        with self.connect() as db:
            rows = db.execute("SELECT COALESCE(display_id,local_id) AS resource_id,kind FROM resource_aliases "
                              "WHERE owner=? AND credential_scope=? ORDER BY local_id",
                              (owner, scope)).fetchall()
        return [dict(row) for row in rows]

    def resolve_resource(self, owner, scope, local_id):
        with self.connect() as db:
            row = db.execute("SELECT remote_id FROM resource_aliases WHERE owner=? "
                             "AND credential_scope=? AND (local_id=? OR display_id=?)",
                             (owner, scope, local_id, local_id)).fetchone()
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


    def relevant_memory_rows(self, owner):
        """Only committed normal+consent references; no remote orphan import."""
        with self.connect() as db:
            return [dict(row) for row in db.execute("""
                SELECT DISTINCT m.* FROM memories m JOIN confirmations c
                ON m.owner=c.owner AND m.memory_id=json_extract(
                  CASE WHEN json_valid(c.result) THEN c.result ELSE '{}' END, '$.memory_id')
                WHERE c.owner=? AND c.decision='normal' AND c.consent=1
                  AND m.local_persisted=1
                ORDER BY m.created_at DESC, m.memory_id ASC
            """, (owner,)).fetchall()]

    def has_memory_confirmation(self, owner, memory_id):
        with self.connect() as db:
            return db.execute("""SELECT 1 FROM confirmations WHERE owner=?
                AND decision='normal' AND consent=1 AND json_extract(
                CASE WHEN json_valid(result) THEN result ELSE '{}' END,'$.memory_id')=?
                LIMIT 1""", (owner, memory_id)).fetchone() is not None
