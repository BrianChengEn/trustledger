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
                    memory_id TEXT PRIMARY KEY, owner TEXT, summary TEXT, created_at TEXT);
            """)

    def connect(self):
        connection = sqlite3.connect(self.filename, timeout=5)
        connection.row_factory = sqlite3.Row
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
