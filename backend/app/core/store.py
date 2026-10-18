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
        filename.parent.mkdir(parents=True, exist_ok=True)
        self.filename = filename
        self.lock = threading.Lock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS confirmations (
                    owner TEXT, alert_id TEXT, decision TEXT, consent INTEGER, result TEXT,
                    PRIMARY KEY(owner, alert_id));
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY, owner TEXT, summary TEXT, created_at TEXT,
                    source TEXT NOT NULL DEFAULT 'local-fallback', assistant_id TEXT);
                CREATE TABLE IF NOT EXISTS assistants (
                    owner TEXT PRIMARY KEY, assistant_id TEXT NOT NULL);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(memories)")}
            if "source" not in columns:
                db.execute(
                    "ALTER TABLE memories ADD COLUMN source TEXT NOT NULL DEFAULT 'local-fallback'")
            if "assistant_id" not in columns:
                db.execute("ALTER TABLE memories ADD COLUMN assistant_id TEXT")

    def connect(self):
        connection = sqlite3.connect(self.filename, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def status(self, owner: str, alert_id: str) -> str:
        with self.connect() as db:
            row = db.execute("SELECT decision FROM confirmations WHERE owner=? AND alert_id=?",
                             (owner, alert_id)).fetchone()
            return row["decision"] if row else "open"

    def replay_confirmation(self, owner, alert_id, decision, consent, request_id) -> Confirmation | None:
        with self.connect() as db:
            existing = db.execute("SELECT * FROM confirmations WHERE owner=? AND alert_id=?",
                                  (owner, alert_id)).fetchone()
        if existing is None:
            return None
        if existing["decision"] != decision or bool(existing["consent"]) != consent:
            raise ConflictingConfirmation()
        return Confirmation.model_validate_json(existing["result"]).model_copy(
            update={"request_id": request_id})

    def confirm(self, owner, alert_id, decision, consent, sentence, request_id, *,
                memory_id=None, source="local-fallback", assistant_id=None,
                memory_status=None) -> Confirmation:
        if source not in {"backboard", "local-fallback"}:
            source = "local-fallback"
        with self.lock, self.connect() as db:
            existing = db.execute("SELECT * FROM confirmations WHERE owner=? AND alert_id=?",
                                  (owner, alert_id)).fetchone()
            if existing:
                if existing["decision"] != decision or bool(existing["consent"]) != consent:
                    raise ConflictingConfirmation()
                return Confirmation.model_validate_json(existing["result"]).model_copy(
                    update={"request_id": request_id})
            saved_id = None
            if sentence:
                saved_id = memory_id or "mem_" + uuid4().hex
                db.execute(
                    """INSERT INTO memories
                       (memory_id, owner, summary, created_at, source, assistant_id)
                       VALUES (?,?,?,?,?,?)""",
                    (saved_id, owner, sentence, datetime.now(timezone.utc).isoformat(),
                     source, assistant_id))
            if memory_status is None:
                memory_status = "written" if sentence else ("skipped" if consent else "not-requested")
            result = Confirmation(alert_id=alert_id, decision=decision, memory_id=saved_id,
                                  memory_status=memory_status, request_id=request_id)
            db.execute("INSERT INTO confirmations VALUES (?,?,?,?,?)", (
                owner, alert_id, decision, int(consent), result.model_dump_json()))
            return result

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
                """SELECT memory_id, source, assistant_id FROM memories
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

    def delete_memory(self, owner, memory_id) -> bool:
        with self.lock, self.connect() as db:
            return db.execute("DELETE FROM memories WHERE owner=? AND memory_id=?",
                              (owner, memory_id)).rowcount > 0
