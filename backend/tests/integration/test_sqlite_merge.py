"""Regression coverage for the PR #9 SQLite / memory integration boundary."""
import sqlite3

import pytest

from app.core.store import Store
from app.core.transactions import (
    SQLiteTransactionProvider, TransactionService, UserContext, ProviderMalformedData,
    ProviderUnavailable,
)
from app.core.rules import analyze as authoritative
from app.services.ai.rules import analyze as direct
from app.adapters.synthetic import load_transactions

SENTENCE = "The demo user explicitly confirmed a streaming alert as normal. Recheck future evidence."


def test_sqlite_provider_is_live_scoped_and_has_no_fixture_fallback(client):
    state = client.app.state
    assert not hasattr(state, "transactions")
    owner = state.settings.demo_user_id
    provider = SQLiteTransactionProvider(state.store, owner)
    service = TransactionService(provider, UserContext(owner))
    tx = service.get_transaction("txn_syn_004")
    assert provider.list_transactions(UserContext("other")) == []
    assert provider.get_transaction(UserContext("other"), tx.id) is None
    with state.store.connect() as db:
        db.execute("UPDATE demo_transactions SET amount_cents=999 WHERE owner=? AND id=?", (owner, tx.id))
    assert service.get_transaction(tx.id).amount == 9.99
    assert client.get("/api/v1/transactions?limit=100").status_code == 200
    with state.store.connect() as db:
        db.execute("DROP TABLE demo_transactions")
    with pytest.raises(ProviderUnavailable):
        service.list_transactions()
    assert service.health().data_mode == "degraded"
    assert client.get("/api/v1/transactions").status_code == 500


def test_sqlite_provider_revalidates_timestamp(client):
    state = client.app.state
    with state.store.connect() as db:
        db.execute("UPDATE demo_transactions SET occurred_at='2026-10-17T00:00:00' WHERE id='txn_syn_004'")
    service = TransactionService(SQLiteTransactionProvider(state.store, state.settings.demo_user_id),
                                 UserContext(state.settings.demo_user_id))
    with pytest.raises(ProviderMalformedData):
        service.list_transactions()


@pytest.mark.parametrize("remote_status", ["failed", "pending", "written"])
def test_local_completion_independent_of_remote_delivery(tmp_path, remote_status):
    store = Store(tmp_path / "memory.db")
    receipt, created = store.claim_confirmation("owner", "alert", "normal", True, True, "rid")
    assert created and store.status("owner", "alert") == "normal"
    local_id = store.prepare_memory_job("owner", "alert", "assistant", SENTENCE)
    assert store.consented_memory_summaries("owner") == []
    store.record_memory_baseline("owner", "alert", [])
    # Even after dispatch begins, preparation is not a completed local receipt.
    assert store.consented_memory_summaries("owner") == []
    receipt = store.finish_memory("owner", receipt, SENTENCE, memory_id=local_id,
                                  memory_status=remote_status)
    reopened = Store(store.filename)
    assert receipt.memory_status == remote_status
    assert reopened.consented_memory_summaries("owner") == [SENTENCE]
    assert reopened.consented_memory_summaries("other") == []
    with reopened.connect() as db:
        db.execute("UPDATE confirmations SET consent=0 WHERE owner='owner'")
    assert reopened.consented_memory_summaries("owner") == []


def test_failed_local_finish_never_matches_prepared_row(tmp_path):
    store = Store(tmp_path / "memory.db")
    receipt, _ = store.claim_confirmation("owner", "alert", "normal", True, True, "rid")
    local_id = store.prepare_memory_job("owner", "alert", "assistant", SENTENCE)
    with store.connect() as db:
        db.execute("CREATE TRIGGER fail_finish BEFORE UPDATE ON memories BEGIN SELECT RAISE(ABORT, 'test'); END")
    result = store.finish_memory("owner", receipt, SENTENCE, memory_id=local_id, memory_status="failed")
    assert result.memory_status == "pending"
    assert store.status("owner", "alert") == "normal"
    assert store.consented_memory_summaries("owner") == []


def test_legacy_memory_migration_requires_successful_owner_receipt(tmp_path):
    from app.schemas.api import Confirmation
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE memories(memory_id TEXT PRIMARY KEY,owner TEXT,summary TEXT,created_at TEXT)")
        db.execute("CREATE TABLE confirmations(owner TEXT,alert_id TEXT,decision TEXT,consent INTEGER,result TEXT,PRIMARY KEY(owner,alert_id))")
        for status in ["written", "failed", "pending"]:
            receipt = Confirmation(alert_id=status, decision="normal", memory_id=status,
                                   memory_status=status, request_id="rid")
            db.execute("INSERT INTO memories VALUES(?,?,?,?)", (status, "owner", SENTENCE, "2026-10-17T00:00:00Z"))
            db.execute("INSERT INTO confirmations VALUES(?,?,?,?,?)", ("owner", status, "normal", 1, receipt.model_dump_json()))
    store = Store(path)
    assert store.consented_memory_summaries("owner") == [SENTENCE]
    assert Store(path).consented_memory_summaries("owner") == [SENTENCE]


def test_unexpected_optional_memory_error_preserves_confirmation(client, monkeypatch):
    from pydantic import SecretStr
    client.app.state.settings.backboard_api_key = SecretStr("synthetic-key")

    async def failed(*args, **kwargs):
        assert client.app.state.store.status("demo-user-001", "alert_txn_syn_004") == "normal"
        raise RuntimeError("private-marker")

    monkeypatch.setattr("app.api.routes.write_consented_memory", failed)
    path = "/api/v1/alerts/alert_txn_syn_004/confirmations"
    body = {"decision": "normal", "consent_to_memory": True}
    response = client.post(path, json=body)
    assert response.status_code == 200 and response.json()["memory_status"] == "pending"
    assert "private-marker" not in response.text
    assert client.post(path, json=body).json()["memory_status"] == "pending"
    assert client.post(path, json={**body, "decision": "review"}).status_code == 409


def test_authoritative_rules_do_not_adopt_direct_service_policy():
    tx = load_transactions()[3]
    different_merchant = tx.model_copy(update={"id": "other", "merchant_display": "Different"})
    assert authoritative(tx, [different_merchant], "rid").alert_type == "none"
    assert direct(tx, [different_merchant], "rid").alert_type == "duplicate"
    high = tx.model_copy(update={"amount": 300, "is_subscription": False})
    previous = tx.model_copy(update={"id": "other", "amount": 200, "is_subscription": False})
    assert authoritative(high, [previous], "rid").alert_type == "amount_anomaly"
    assert direct(high, [previous], "rid").alert_type == "none"
