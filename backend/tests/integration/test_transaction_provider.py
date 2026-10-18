"""Mock canonical adapter outputs only; no Nessie URLs or upstream response mappings."""
import logging
import warnings

import pytest
from pydantic import ValidationError

from app.adapters.synthetic import load_transactions
from app.api.dependencies import get_transaction_provider
from app.core.config import Settings
from app.core.transactions import (
    AdapterHealth, ProviderMalformedData, ProviderTimeout, ProviderUnavailable,
    SyntheticTransactionProvider, TransactionNotFound, TransactionService, UserContext,
)
from app.schemas.api import ErrorEnvelope
from app.schemas.transaction import Transaction

PRIVATE = "synthetic-private-provider-marker"


class MockNessieProvider:
    def __init__(self):
        self.rows = [tx.model_copy(update={"id": tx.id.replace("syn", "mock"), "source": "nessie"})
                     for tx in load_transactions()]
        self.calls = []

    def list_transactions(self, user_context, limit=25):
        self.calls.append(("list", user_context, limit))
        return sorted(self.rows, key=lambda tx: tx.occurred_at, reverse=True)[:limit]

    def get_transaction(self, user_context, transaction_id):
        self.calls.append(("get", user_context, transaction_id))
        return next((tx for tx in self.rows if tx.id == transaction_id), None)

    def health(self):
        # A mock must never claim live Nessie connectivity.
        return AdapterHealth(status="degraded", data_mode="degraded")


@pytest.fixture
def provider(client):
    mock = MockNessieProvider()
    client.app.dependency_overrides[get_transaction_provider] = lambda: mock
    yield mock
    client.app.dependency_overrides.clear()


def assert_safe_error(response, status=500, code="internal_error"):
    assert response.status_code == status
    payload = ErrorEnvelope.model_validate(response.json())
    assert payload.error.code == code
    assert payload.error.request_id == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert PRIVATE not in response.text


def test_synthetic_baseline_order_and_health(client):
    expected = sorted(load_transactions(), key=lambda tx: tx.occurred_at, reverse=True)
    assert client.get("/api/v1/transactions").json() == [tx.model_dump(mode="json") for tx in expected]
    assert [row["alert_id"] for row in client.get("/api/v1/alerts").json()] == [
        "alert_txn_syn_004", "alert_txn_syn_005", "alert_txn_syn_008"]
    assert client.get("/api/v1/health").json()["data_mode"] == "synthetic"


def test_mock_switches_all_transaction_paths(client, provider):
    rows = client.get("/api/v1/transactions?limit=2&user_id=untrusted",
                      headers={"x-user-id": "untrusted"}).json()
    assert len(rows) == 2 and all(row["source"] == "nessie" for row in rows)
    assert all(row["id"].startswith("txn_mock_") for row in rows)
    assert provider.calls[0][2] == 2
    assert client.get("/api/v1/health").json()["data_mode"] == "degraded"
    response = client.post("/api/v1/analyses", json={"transaction_id": "txn_mock_004"})
    assert response.status_code == 200 and response.json()["alert_type"] == "duplicate"
    preview = client.get("/api/v1/privacy/preview/txn_mock_004").json()
    assert preview["safe_payload"]["same_category_same_amount_24h_count"] == 2
    assert "txn_mock" not in str(preview["safe_payload"])
    alerts = client.get("/api/v1/alerts").json()
    assert {a["alert_id"] for a in alerts} == {
        "alert_txn_mock_004", "alert_txn_mock_005", "alert_txn_mock_008"}
    provider.calls.clear()
    confirmation = client.post("/api/v1/alerts/alert_txn_mock_004/confirmations",
                               json={"decision": "normal", "consent_to_memory": True})
    assert confirmation.status_code == 200
    assert confirmation.json()["memory_status"] == "written"
    assert [call[0] for call in provider.calls] == ["list", "get"]
    assert all(call[1] == UserContext(client.app.state.settings.demo_user_id) for call in provider.calls)
    assert client.get("/api/v1/memories").json()[0]["source"] == "local-fallback"
    assert client.delete("/api/v1/memories/" + confirmation.json()["memory_id"]).status_code == 204
    assert_safe_error(client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}),
                      404, "not_found")
    client.app.dependency_overrides.clear()
    assert client.get("/api/v1/transactions").json()[0]["source"] == "synthetic"


def test_empty_provider_does_not_fall_back(client, provider):
    provider.rows = []
    assert client.get("/api/v1/transactions").json() == []
    assert client.get("/api/v1/alerts").json() == []
    assert_safe_error(client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}),
                      404, "not_found")
    assert_safe_error(client.get("/api/v1/privacy/preview/txn_syn_004"), 404, "not_found")
    assert_safe_error(client.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                                 json={"decision": "normal", "consent_to_memory": True}),
                      404, "not_found")


@pytest.mark.parametrize("failure", [ProviderUnavailable, ProviderTimeout, ProviderMalformedData,
                                     TimeoutError, RuntimeError])
@pytest.mark.parametrize("method,path,body", [
    ("get", "/transactions", None), ("get", "/alerts", None),
    ("post", "/analyses", {"transaction_id": "txn_mock_004"}),
    ("get", "/privacy/preview/txn_mock_004", None),
    ("post", "/alerts/alert_txn_mock_004/confirmations",
     {"decision": "normal", "consent_to_memory": True}),
])
def test_provider_failures_are_safe(client, provider, monkeypatch, caplog, failure, method, path, body):
    def fail(*args):
        raise failure(PRIVATE)
    monkeypatch.setattr(provider, "list_transactions", fail)
    caplog.set_level(logging.INFO, logger="app.core.http")
    response = client.request(method, "/api/v1" + path, json=body,
                              headers={"origin": "http://localhost:5173"})
    assert_safe_error(response)
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert PRIVATE not in caplog.text
    assert client.get("/api/v1/memories").json() == []


@pytest.mark.parametrize("failure", [ProviderUnavailable, ProviderTimeout, ProviderMalformedData,
                                     TimeoutError, RuntimeError, TransactionNotFound])
def test_get_failures(client, provider, monkeypatch, failure):
    def fail(*args):
        raise failure(PRIVATE)
    monkeypatch.setattr(provider, "get_transaction", fail)
    response = client.get("/api/v1/privacy/preview/txn_mock_004")
    if failure is TransactionNotFound:
        assert_safe_error(response, 404, "not_found")
    else:
        assert_safe_error(response)


@pytest.mark.parametrize("bad", [None, {}, "raw", [None], [{"raw_account_id": PRIVATE}]])
def test_malformed_list(client, provider, monkeypatch, bad):
    monkeypatch.setattr(provider, "list_transactions", lambda *args: bad)
    assert_safe_error(client.get("/api/v1/transactions"))


@pytest.mark.parametrize("field,value", [("occurred_at", "2026-10-17T12:00:00"),
                                         ("account_token", PRIVATE), ("amount", -1)])
def test_invalid_canonical_model_revalidated(client, provider, monkeypatch, field, value):
    bad = provider.rows[0].model_copy(update={field: value})
    monkeypatch.setattr(provider, "list_transactions", lambda *args: [bad])
    assert_safe_error(client.get("/api/v1/transactions"))


def test_duplicate_ids_and_limit_violation(client, provider, monkeypatch):
    monkeypatch.setattr(provider, "list_transactions", lambda *args: [provider.rows[0]] * 2)
    assert_safe_error(client.get("/api/v1/transactions"))
    monkeypatch.setattr(provider, "list_transactions", lambda *args: provider.rows)
    assert_safe_error(client.get("/api/v1/transactions?limit=1"))


@pytest.mark.parametrize("change", ["different_id", "different_amount", "absent_from_list"])
def test_list_get_consistency_before_confirmation(client, provider, monkeypatch, change):
    original = provider.rows[3]
    replacement = original.model_copy(update={
        "id": "txn_wrong" if change == "different_id" else original.id,
        "amount": 999 if change == "different_amount" else original.amount,
    })
    monkeypatch.setattr(provider, "get_transaction", lambda *args: replacement)
    if change == "absent_from_list":
        provider.rows = []
    response = client.post("/api/v1/analyses", json={"transaction_id": original.id})
    assert_safe_error(response)
    if change != "absent_from_list":
        response = client.post("/api/v1/alerts/alert_txn_mock_004/confirmations",
                               json={"decision": "normal", "consent_to_memory": True})
        assert_safe_error(response)
    assert client.get("/api/v1/memories").json() == []


@pytest.mark.parametrize("failure", [ProviderUnavailable, ProviderTimeout, ProviderMalformedData,
                                     TimeoutError, RuntimeError])
def test_health_failure_is_degraded(client, provider, monkeypatch, failure):
    def fail():
        raise failure(PRIVATE)
    monkeypatch.setattr(provider, "health", fail)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == response.json()["data_mode"] == "degraded"
    assert PRIVATE not in response.text


@pytest.mark.parametrize("value", [None, {"status": "ok", "data_mode": "mock"},
                                    {"status": "ok", "data_mode": "synthetic", "raw": PRIVATE}])
def test_invalid_health_is_degraded(client, provider, monkeypatch, value):
    monkeypatch.setattr(provider, "health", lambda: value)
    assert client.get("/api/v1/health").json()["data_mode"] == "degraded"


@pytest.mark.parametrize("mode", ["live", "nessie", "mock", "unknown"])
def test_invalid_factory_modes_fail_closed(mode):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, transaction_provider=mode)


def test_synthetic_provider_owner_scope():
    provider = SyntheticTransactionProvider(load_transactions(), "demo-owner")
    assert provider.list_transactions(UserContext("other")) == []
    assert provider.get_transaction(UserContext("other"), "txn_syn_004") is None
    rows = provider.list_transactions(UserContext("demo-owner"))
    for row in rows:
        assert provider.get_transaction(UserContext("demo-owner"), row.id) == row


@pytest.mark.parametrize("failure,category", [(TimeoutError, ProviderTimeout),
                                              (RuntimeError, ProviderUnavailable)])
def test_internal_failure_categories(failure, category):
    provider = MockNessieProvider()

    def fail(*args):
        raise failure(PRIVATE)
    provider.list_transactions = fail
    with pytest.raises(category) as error:
        TransactionService(provider, UserContext("demo")).list_transactions()
    assert PRIVATE not in str(error.value)


def test_canonical_dicts_accepted_without_upstream_mapping(client, provider, monkeypatch):
    rows = [row.model_dump() for row in provider.rows]
    monkeypatch.setattr(provider, "list_transactions", lambda *args: rows)
    response = client.get("/api/v1/transactions")
    assert response.status_code == 200
    assert all(Transaction.model_validate(row).source == "nessie" for row in response.json())


def test_invalid_model_serialization_does_not_warn_with_raw_input(client, provider, monkeypatch):
    bad = provider.rows[0].model_copy(update={"occurred_at": PRIVATE})
    monkeypatch.setattr(provider, "list_transactions", lambda *args: [bad])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert_safe_error(client.get("/api/v1/transactions"))
    assert not caught


def test_provider_dependency_resolved_once_per_request(client):
    calls = []

    def resolve():
        calls.append(True)
        return MockNessieProvider()

    client.app.dependency_overrides[get_transaction_provider] = resolve
    response = client.post("/api/v1/alerts/alert_txn_mock_004/confirmations",
                           json={"decision": "normal", "consent_to_memory": False})
    assert response.status_code == 200 and response.json()["memory_status"] == "not-requested"
    assert len(calls) == 1
    assert client.get("/api/v1/memories").json() == []


def test_health_does_not_fetch_transactions(client, provider, monkeypatch):
    def fail(*args):
        raise AssertionError("Health must only use the provider health method")
    monkeypatch.setattr(provider, "list_transactions", fail)
    monkeypatch.setattr(provider, "get_transaction", fail)
    assert client.get("/api/v1/health").status_code == 200


def test_context_window_and_get_outside_window():
    provider = MockNessieProvider()
    tx = provider.rows[0]
    provider.rows = [tx.model_copy(update={"id": f"txn_mock_{i}"}) for i in range(101)]
    service = TransactionService(provider, UserContext("demo"))
    assert len(service.history()) == 100
    assert service.get_transaction("txn_mock_100").id == "txn_mock_100"
    assert [call[0] for call in provider.calls] == ["list", "get"]
