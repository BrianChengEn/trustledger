import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from pydantic import ValidationError

from app.core.store import ConflictingConfirmation, Store

SUMMARY = "The demo user confirmed a synthetic alert as normal."


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "store.db")


def confirm(store, decision="normal", consent=True, request_id="request", enabled=True):
    return store.confirm("owner", "alert", decision, consent, SUMMARY, request_id,
                         memory_enabled=enabled)


def test_confirmation_committed_before_optional_write(store, monkeypatch):
    def fail(owner, sentence, result):
        reopened = Store(store.filename)
        assert reopened.status(owner, result.alert_id) == "normal"
        with reopened.connect() as db:
            row = db.execute("SELECT result FROM confirmations").fetchone()
            assert '"memory_status":"pending"' in row["result"]
        raise RuntimeError("private-synthetic-write-error")
    monkeypatch.setattr(store, "_write_memory", fail)
    result = confirm(store)
    assert result.memory_status == "failed" and result.memory_id is None
    reopened = Store(store.filename)
    assert reopened.status("owner", "alert") == "normal"
    assert confirm(reopened, request_id="replay").memory_status == "failed"
    assert reopened.list_memories("owner") == []


def test_success_survives_reopen_and_repeat(store):
    result = confirm(store)
    assert result.memory_status == "written"
    reopened = Store(store.filename)
    replay = confirm(reopened, request_id="new-request")
    assert replay.memory_id == result.memory_id
    assert replay.request_id == "new-request"
    assert reopened.status("owner", "alert") == "normal"
    assert len(reopened.list_memories("owner")) == 1
    with reopened.connect() as db:
        assert db.execute("SELECT count(*) FROM confirmations").fetchone()[0] == 1


@pytest.mark.parametrize("target", ["insert", "outcome"])
def test_sql_failure_rolls_back_only_optional_transaction(store, target):
    with store.connect() as db:
        if target == "insert":
            db.execute("""CREATE TRIGGER fail_memory BEFORE INSERT ON memories
                          BEGIN SELECT RAISE(ABORT, 'private-synthetic-marker'); END""")
        else:
            db.execute("""CREATE TRIGGER fail_outcome BEFORE UPDATE ON confirmations
                          WHEN json_extract(NEW.result, '$.memory_status') = 'written'
                          BEGIN SELECT RAISE(ABORT, 'private-synthetic-marker'); END""")
    result = confirm(store)
    assert result.memory_status == "failed" and result.memory_id is None
    assert store.status("owner", "alert") == "normal"
    assert store.list_memories("owner") == []  # Includes rollback after the memory INSERT succeeded.
    assert confirm(Store(store.filename)).memory_status == "failed"


def test_unpersistable_failure_retains_pending_without_retry(store):
    with store.connect() as db:
        db.execute("""CREATE TRIGGER fail_update BEFORE UPDATE ON confirmations
                      BEGIN SELECT RAISE(ABORT, 'private-synthetic-marker'); END""")
    result = confirm(store)
    assert result.memory_status == "pending" and result.memory_id is None
    assert store.status("owner", "alert") == "normal"
    assert store.list_memories("owner") == []
    with store.connect() as db:
        db.execute("DROP TRIGGER fail_update")
    replay = confirm(Store(store.filename))
    assert replay.memory_status == "pending"
    assert store.list_memories("owner") == []


def test_interruption_after_confirmation_does_not_backfill(store, monkeypatch):
    class Interrupted(BaseException):
        pass

    def interrupt(*args):
        raise Interrupted()
    monkeypatch.setattr(store, "_write_memory", interrupt)
    with pytest.raises(Interrupted):
        confirm(store)
    reopened = Store(store.filename)
    assert reopened.status("owner", "alert") == "normal"
    assert confirm(reopened).memory_status == "pending"
    assert reopened.list_memories("owner") == []


def test_confirmation_insert_failure_creates_no_memory(store):
    with store.connect() as db:
        db.execute("""CREATE TRIGGER fail_confirmation BEFORE INSERT ON confirmations
                      BEGIN SELECT RAISE(ABORT, 'synthetic-failure'); END""")
    with pytest.raises(sqlite3.Error):
        confirm(store)
    assert store.status("owner", "alert") == "open"
    assert store.list_memories("owner") == []


@pytest.mark.parametrize("decision,consent,enabled,status", [
    ("normal", True, True, "written"), ("normal", False, True, "not-requested"),
    ("normal", True, False, "skipped"), ("review", True, True, "skipped"),
    ("review", False, True, "not-requested"), ("review", True, False, "skipped"),
])
def test_store_enforces_gates_even_with_sentence(store, decision, consent, enabled, status):
    result = confirm(store, decision, consent, enabled=enabled)
    assert result.memory_status == status
    assert len(store.list_memories("owner")) == (1 if status == "written" else 0)
    assert store.status("owner", "alert") == decision


@pytest.mark.parametrize("decision,consent", [("fraud", True), ("", True), (None, True),
                                             ("normal", "true"), ("normal", 1), ("normal", None)])
def test_invalid_outcome_or_consent_rejected_at_store(store, decision, consent):
    with pytest.raises(ValidationError):
        confirm(store, decision, consent)
    assert store.status("owner", "alert") == "open"
    assert store.list_memories("owner") == []


def test_disabled_write_not_backfilled_when_enabled(store):
    assert confirm(store, enabled=False).memory_status == "skipped"
    assert confirm(store, enabled=True).memory_status == "skipped"
    assert store.list_memories("owner") == []


@pytest.mark.parametrize("decision,consent", [("review", True), ("normal", False), ("review", False)])
def test_conflicts_preserve_original(store, decision, consent):
    original = confirm(store)
    with pytest.raises(ConflictingConfirmation):
        confirm(Store(store.filename), decision, consent)
    assert confirm(store).memory_id == original.memory_id
    assert store.status("owner", "alert") == "normal"


def test_owner_scope_and_deleted_memory_not_recreated(store):
    first = confirm(store)
    other = store.confirm("other", "alert", "normal", True, SUMMARY, "other-request")
    assert first.memory_id != other.memory_id
    assert not store.delete_memory("other", first.memory_id)
    assert store.delete_memory("owner", first.memory_id)
    assert not store.delete_memory("owner", first.memory_id)
    assert confirm(store).memory_id == first.memory_id  # Replay is a historical outcome.
    assert store.list_memories("owner") == []
    assert len(store.list_memories("other")) == 1


def test_concurrent_instances_do_not_duplicate_confirmation_or_memory(store):
    stores = [store, Store(store.filename)]
    barrier = Barrier(2)

    def worker(index):
        barrier.wait(timeout=5)
        return confirm(stores[index], request_id=f"request-{index}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, range(2)))
    assert all(result.memory_status in {"pending", "written"} for result in results)
    replay = confirm(Store(store.filename))
    assert replay.memory_status == "written"
    assert len(store.list_memories("owner")) == 1
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM confirmations").fetchone()[0] == 1


def test_concurrent_conflict_has_one_authoritative_winner(store):
    stores = [store, Store(store.filename)]
    barrier = Barrier(2)

    def worker(index):
        barrier.wait(timeout=5)
        try:
            return confirm(stores[index], decision=["normal", "review"][index]).decision
        except ConflictingConfirmation:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, range(2)))
    assert results.count("conflict") == 1
    decision = store.status("owner", "alert")
    assert decision in results
    assert len(store.list_memories("owner")) == (1 if decision == "normal" else 0)


def test_connections_are_closed_after_transaction(store):
    with store.connect() as connection:
        assert connection.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
