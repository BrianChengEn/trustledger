import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas.api import Confirmation, ConfirmationRequest, MemorySummary


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

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.filename, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

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
            try:
                return self._write_memory(owner, sentence, result)
            except Exception:
                # Do not expose SQL/summary/exception text. Insert + outcome update
                # roll back together, leaving the original confirmation intact.
                failed = result.model_copy(update={"memory_status": "failed"})
                try:
                    with self.connect() as db:
                        db.execute("UPDATE confirmations SET result=? WHERE owner=? AND alert_id=?",
                                   (failed.model_dump_json(), owner, alert_id))
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
            db.execute("INSERT INTO memories VALUES (?,?,?,?)", (
                memory.memory_id, owner, memory.summary, memory.created_at.isoformat()))
            db.execute("UPDATE confirmations SET result=? WHERE owner=? AND alert_id=?",
                       (written.model_dump_json(), owner, result.alert_id))
        return written

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
