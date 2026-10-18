"""F5 HTTP integration with canonical F3 and deterministic F4 providers only."""
import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.adapters.synthetic import load_transactions
from app.api.dependencies import get_fraud_provider, get_transaction_provider
from app.core.config import Settings
from app.core.fraud import MockJevProvider, MockScenario
from app.core.transactions import SyntheticTransactionProvider
from app.main import create_app
from app.schemas.api import Analysis, SafePayload
from app.core.rules import analyze


class SpyFraudProvider(MockJevProvider):
    def __init__(self, scenario=MockScenario.VALID):
        super().__init__(scenario)
        self.inputs = []

    def assess(self, features):
        self.inputs.append(features.model_dump())
        return super().assess(features)


class SpyTransactionProvider(SyntheticTransactionProvider):
    def __init__(self, rows, owner):
        super().__init__(rows, owner)
        self.calls = []

    def list_transactions(self, user_context, limit=25):
        self.calls.append(("list", user_context.user_id))
        return super().list_transactions(user_context, limit)

    def get_transaction(self, user_context, transaction_id):
        self.calls.append(("get", user_context.user_id))
        return super().get_transaction(user_context, transaction_id)


def install(client, provider, rows=None):
    rows = load_transactions() if rows is None else rows
    transactions = SpyTransactionProvider(rows, client.app.state.settings.demo_user_id)
    client.app.dependency_overrides[get_transaction_provider] = lambda: transactions
    client.app.dependency_overrides[get_fraud_provider] = lambda: provider
    return transactions


@pytest.mark.parametrize("scenario", list(MockScenario))
@pytest.mark.parametrize("index", [0, 3, 4, 7])
def test_analysis_pipeline_success_and_fallback(client, scenario, index):
    provider = SpyFraudProvider(scenario)
    transactions = install(client, provider)
    tx = transactions.transactions[index]
    response = client.post("/api/v1/analyses", json={"transaction_id": tx.id},
                           headers={"origin": "http://localhost:5173", "x-user-id": "ignored"})
    assert response.status_code == 200
    expected = analyze(tx, transactions.transactions, response.headers["x-request-id"]).model_dump()
    if scenario != MockScenario.VALID:
        expected["provider_mode"] = "degraded"
    assert response.json() == expected
    Analysis.model_validate(response.json())
    assert len(provider.inputs) == 1
    assert transactions.calls == [("list", client.app.state.settings.demo_user_id),
                                  ("get", client.app.state.settings.demo_user_id)]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert client.get("/api/v1/memories").json() == []
    assert client.app.state.store.status(client.app.state.settings.demo_user_id, "alert_" + tx.id) == "open"


@pytest.mark.parametrize("rows", [[], None])
def test_unknown_or_empty_data_never_calls_fraud(client, rows):
    provider = SpyFraudProvider()
    install(client, provider, rows)
    response = client.post("/api/v1/analyses", json={"transaction_id": "missing"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert provider.inputs == []


def test_no_prior_transactions_still_uses_rules(client):
    provider = SpyFraudProvider(MockScenario.TIMEOUT)
    tx = load_transactions()[4]
    install(client, provider, [tx])
    response = client.post("/api/v1/analyses", json={"transaction_id": tx.id})
    assert response.status_code == 200
    assert response.json()["alert_type"] == "amount_anomaly"
    assert response.json()["severity"] == "high" and response.json()["needs_human"] is True
    assert response.json()["provider_mode"] == "degraded"
    assert provider.inputs[0]["same_category_same_amount_24h_count"] == 1


def test_provider_input_matches_preview_and_excludes_raw_sentinels(client):
    provider = SpyFraudProvider()
    tx = load_transactions()[4].model_copy(update={
        "id": "txn_private_marker", "account_token": "acct_private_marker",
        "merchant_display": "PRIVATE PERSON key=synthetic-sentinel",
        "merchant_category": "raw-private-category",
    })
    install(client, provider, [tx])
    response = client.post("/api/v1/analyses", json={"transaction_id": tx.id})
    assert response.status_code == 200
    preview = client.get("/api/v1/privacy/preview/" + tx.id)
    assert preview.status_code == 200
    assert provider.inputs == [preview.json()["safe_payload"]]
    assert set(provider.inputs[0]) == set(SafePayload.model_fields)
    assert provider.inputs[0]["merchant_category"] == "other"
    for value in [tx.id, tx.account_token, tx.merchant_display, "synthetic-sentinel", "849", "2026-",
                  response.headers["x-request-id"]]:
        assert value not in str(provider.inputs)


@pytest.mark.parametrize("scenario", [MockScenario.VALID, MockScenario.TIMEOUT])
def test_alert_confirmation_and_memory_consistency_without_extra_calls(client, scenario):
    provider = SpyFraudProvider(scenario)
    transactions = install(client, provider)
    analysis = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
    alerts = client.get("/api/v1/alerts").json()
    assert [a["alert_id"] for a in alerts] == ["alert_txn_syn_004", "alert_txn_syn_005", "alert_txn_syn_008"]
    alert = alerts[0]
    for key in ["transaction_id", "alert_type", "severity", "needs_human", "confidence", "evidence", "model_version"]:
        assert alert[key] == analysis[key]
    assert alert["provider_mode"] == "rules-only"  # No provider attempt on GET.
    assert client.get("/api/v1/health").json()["analysis_mode"] == "rules-only"
    assert client.get("/api/v1/transactions").status_code == 200
    assert client.get("/api/v1/privacy/preview/txn_syn_004").status_code == 200
    transactions.calls.clear()
    body = {"decision": "normal", "consent_to_memory": True}
    confirmation = client.post("/api/v1/alerts/alert_txn_syn_004/confirmations", json=body)
    assert confirmation.status_code == 200 and confirmation.json()["memory_status"] == "written"
    assert [call[0] for call in transactions.calls] == ["list", "get"]
    repeat = client.post("/api/v1/alerts/alert_txn_syn_004/confirmations", json=body)
    assert repeat.json()["memory_id"] == confirmation.json()["memory_id"]
    assert client.get("/api/v1/alerts").json()[0]["status"] == "normal"
    assert len(client.get("/api/v1/memories").json()) == 1
    assert client.delete("/api/v1/memories/" + confirmation.json()["memory_id"]).status_code == 204
    assert client.get("/api/v1/memories").json() == []
    assert len(provider.inputs) == 1  # Only the original POST analyses invokes the provider.


@pytest.mark.parametrize("bad", [None, {"severity": 1.89}, {"raw_body": "private-synthetic-marker"}])
def test_invalid_assessment_is_not_exposed(client, bad, caplog):
    class Provider:
        def assess(self, features):
            return bad
    install(client, Provider())
    caplog.set_level(logging.INFO, logger="app.core.http")
    response = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_005"})
    assert response.status_code == 200
    assert response.json()["provider_mode"] == "degraded"
    assert response.json()["severity"] == "high"
    assert "private-synthetic-marker" not in response.text + caplog.text


@pytest.mark.parametrize("failure", [TimeoutError, RuntimeError])
def test_unexpected_exception_and_timeout_are_safe(client, failure, caplog):
    class Provider:
        def assess(self, features):
            raise failure("https://provider.invalid/?key=private-synthetic-marker")
    install(client, Provider())
    caplog.set_level(logging.INFO, logger="app.core.http")
    response = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_005"})
    assert response.status_code == 200
    assert response.json()["provider_mode"] == "degraded"
    assert response.json()["needs_human"] is True
    assert "private-synthetic-marker" not in response.text + caplog.text


def test_successful_mock_cannot_override_rule_severity_or_model_version(client):
    assessment = MockJevProvider().assessment.model_copy(update={"numeric_score": 1.89})
    install(client, MockJevProvider(assessment=assessment))
    response = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_005"})
    assert response.json()["severity"] == "high" and response.json()["confidence"] == 1.0
    assert response.json()["needs_human"] is True
    assert response.json()["model_version"] is None
    assert response.json()["provider_mode"] == "rules-only"
    assert "numeric_score" not in response.json()


@pytest.mark.parametrize("value", ["live", "jev", "unknown"])
def test_provider_config_rejects_live_or_unknown(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, fraud_provider=value)


def test_mock_selection_is_explicit_and_offline(tmp_path, monkeypatch):
    import socket

    def deny_network(*args, **kwargs):
        raise AssertionError("Network calls are forbidden in this phase")
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    settings = Settings(_env_file=None, database_path=tmp_path / "pipeline.db", fraud_provider="mock-jev")
    app = create_app(settings)
    from app.core.fraud import MockJevProvider as Mock
    calls = []
    original = Mock.assess

    def assess(self, features):
        calls.append(features)
        return original(self, features)
    monkeypatch.setattr(Mock, "assess", assess)
    with TestClient(app) as client:
        response = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"})
        assert response.status_code == 200 and len(calls) == 1
        assert response.json()["provider_mode"] == "rules-only"


def test_analysis_never_invokes_store_writes(client, monkeypatch):
    install(client, SpyFraudProvider(MockScenario.UNAVAILABLE))

    def forbidden(*args, **kwargs):
        raise AssertionError("Analysis must not persist confirmation or memory")
    monkeypatch.setattr(client.app.state.store, "confirm", forbidden)
    response = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"})
    assert response.status_code == 200 and response.json()["provider_mode"] == "degraded"
