import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas.api import Confirmation, MemorySummary


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
                CREATE TABLE IF NOT EXISTS confirmations (
                    owner TEXT, alert_id TEXT, decision TEXT, consent INTEGER, result TEXT,
                    PRIMARY KEY(owner, alert_id));
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY, owner TEXT, summary TEXT, created_at TEXT);
                CREATE TABLE IF NOT EXISTS query_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
                    source TEXT NOT NULL CHECK(source IN ('nessie','synthetic')),
                    query_name TEXT NOT NULL CHECK(query_name IN ('customers.list','accounts.list',
                        'accounts.get','accounts.by_customer','deposits.by_account',
                        'withdrawals.by_account')),
                    resource_id TEXT CHECK(resource_id IS NULL OR length(resource_id) IN (24,36)),
                    requested_at TEXT NOT NULL,
                    http_status INTEGER CHECK(http_status BETWEEN 100 AND 599),
                    duration_ms INTEGER NOT NULL CHECK(duration_ms>=0),
                    body_format TEXT NOT NULL CHECK(body_format IN ('json','text','none')),
                    response_body TEXT, transport_error TEXT,
                    CHECK((http_status IS NULL AND body_format='none' AND response_body IS NULL
                           AND transport_error IS NOT NULL) OR
                          (http_status IS NOT NULL AND body_format IN ('json','text')
                           AND response_body IS NOT NULL AND transport_error IS NULL)));
                CREATE INDEX IF NOT EXISTS history_owner ON query_history(owner,id);
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
            schema = db.execute("SELECT sql FROM sqlite_master WHERE name='query_history'").fetchone()[0]
            if "length(resource_id)=24" in schema:
                sequence = db.execute("SELECT seq FROM sqlite_sequence WHERE name='query_history'").fetchone()
                db.execute("BEGIN IMMEDIATE")
                db.execute("ALTER TABLE query_history RENAME TO query_history_legacy")
                db.execute(schema.replace("length(resource_id)=24", "length(resource_id) IN (24,36)"))
                db.execute("INSERT INTO query_history SELECT * FROM query_history_legacy")
                db.execute("DROP TABLE query_history_legacy")
                if sequence:
                    updated = db.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) "
                                         "WHERE name='query_history'", (sequence[0],)).rowcount
                    if not updated:
                        db.execute("INSERT INTO sqlite_sequence VALUES('query_history',?)", (sequence[0],))
                db.execute("CREATE INDEX history_owner ON query_history(owner,id)")
        filename.chmod(0o600)

    def connect(self):
        connection = sqlite3.connect(self.filename, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

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
            memory_id = None
            if sentence:
                memory_id = "mem_" + uuid4().hex
                db.execute("INSERT INTO memories VALUES (?,?,?,?)", (
                    memory_id, owner, sentence, datetime.now(timezone.utc).isoformat()))
            result = Confirmation(alert_id=alert_id, decision=decision, memory_id=memory_id,
                                  memory_status="written" if sentence else (
                                      "skipped" if consent else "not-requested"),
                                  request_id=request_id)
            db.execute("INSERT INTO confirmations VALUES (?,?,?,?,?)", (
                owner, alert_id, decision, int(consent), result.model_dump_json()))
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
        body = result["response_body"]
        if result["body_format"] == "json":
            body = json.dumps(body, ensure_ascii=False, allow_nan=False)
        transport = result["transport_error"]
        with self.lock, self.connect() as db:
            cursor = db.execute("INSERT INTO query_history(owner,source,query_name,resource_id,"
                                "requested_at,http_status,duration_ms,body_format,response_body,"
                                "transport_error) VALUES(?,?,?,?,?,?,?,?,?,?)", (
                owner, result["source"], result["query"], result["resource_id"],
                result["requested_at"], result["http_status"], result["duration_ms"],
                result["body_format"], body, json.dumps(transport) if transport else None))
            history_id = cursor.lastrowid
        return history_id

    @staticmethod
    def history_row(row, *, full=True):
        result = dict(row)
        result.pop("owner")
        result["history_id"] = result.pop("id")
        result["query"] = result.pop("query_name")
        result["transport_error"] = json.loads(result["transport_error"]) if result[
            "transport_error"] else None
        if full:
            if result["body_format"] == "json":
                result["response_body"] = json.loads(result["response_body"])
            result.update(write_status="saved", write_label=None)
        return result

    def list_history(self, owner, before_id=None):
        cursor_clause = " AND id < ?" if before_id is not None else ""
        args = (owner, before_id) if before_id is not None else (owner,)
        with self.connect() as db:
            rows = db.execute("SELECT id,owner,source,query_name,resource_id,requested_at,"
                              "http_status,duration_ms,body_format,transport_error FROM query_history"
                              " WHERE owner=?" + cursor_clause + " ORDER BY id DESC LIMIT 51",
                              args).fetchall()
        return {"items": [self.history_row(r, full=False) for r in rows[:50]],
                "next_cursor": rows[49]["id"] if len(rows) > 50 else None}

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
