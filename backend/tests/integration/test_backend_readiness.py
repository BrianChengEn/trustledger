"""F8 combined-boundary transitions; vendor wire contracts are intentionally absent."""
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.explanation import ExplanationService, MockExplanationProvider
from app.core.fraud import MockScenario
from app.core.transactions import ProviderTimeout, ProviderUnavailable
from app.main import create_app
from app.schemas.api import Analysis, SafePayload
from test_analysis_pipeline import SpyFraudProvider, install
from test_contract import contract as contract
from test_contract import validate


TX = "txn_syn_005"
CONFIRM = f"/api/v1/alerts/alert_{TX}/confirmations"
BODY = {"decision": "normal", "consent_to_memory": True}


def checked(contract, client, method, path, template=None, status=200, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]
    if status == 204:
        assert response.content == b""
    else:
        spec = contract["paths"][template or path][method]["responses"].get(str(status))
        if spec and "$ref" in spec:
            spec = contract["components"]["responses"][spec["$ref"].split("/")[-1]]
        schema = (spec["content"]["application/json"]["schema"] if spec else
                  {"$ref": "#/components/schemas/ErrorEnvelope"})
        validate(contract, schema, response.json())
        if status >= 400:
            assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    return response


@pytest.mark.parametrize("failure", [MockScenario.TIMEOUT, MockScenario.UNAVAILABLE, MockScenario.MALFORMED])
def test_full_workflow_recovers_without_stale_assessment(contract, client, failure):
    fraud = SpyFraudProvider(failure)
    install(client, fraud)
    checked(contract, client, "get", "/api/v1/health")
    rows = checked(contract, client, "get", "/api/v1/transactions").json()
    preview = checked(contract, client, "get", f"/api/v1/privacy/preview/{TX}",
                      "/api/v1/privacy/preview/{transaction_id}").json()
    failed = checked(contract, client, "post", "/api/v1/analyses", json={"transaction_id": TX}).json()
    assert failed["provider_mode"] == "degraded" and failed["needs_human"]
    fraud.scenario = MockScenario.VALID
    recovered = checked(contract, client, "post", "/api/v1/analyses", json={"transaction_id": TX}).json()
    assert recovered["provider_mode"] == "rules-only"
    for key in ("severity", "confidence", "evidence", "model_version", "needs_human", "transaction_id"):
        assert recovered[key] == failed[key]
    assert fraud.inputs == [preview["safe_payload"]] * 2
    assert set(fraud.inputs[0]) == set(SafePayload.model_fields)
    assert len(fraud.inputs[0]) == 8
    assert TX not in str(fraud.inputs)
    assert checked(contract, client, "get", "/api/v1/memories").json() == []
    alerts = checked(contract, client, "get", "/api/v1/alerts").json()
    assert any(a["alert_id"] == "alert_" + TX for a in alerts)
    confirmation = checked(contract, client, "post", CONFIRM,
                           "/api/v1/alerts/{alert_id}/confirmations", json=BODY).json()
    memories = checked(contract, client, "get", "/api/v1/memories").json()
    assert [m["memory_id"] for m in memories] == [confirmation["memory_id"]]
    checked(contract, client, "delete", "/api/v1/memories/" + confirmation["memory_id"],
            "/api/v1/memories/{memory_id}", status=204)
    assert checked(contract, client, "get", "/api/v1/transactions").json() == rows
    assert len(fraud.inputs) == 2
    # F7 remains an internal interface. Reuse the recovered F5 analysis and F4 snapshot.
    explanation = MockExplanationProvider("timeout")
    service = ExplanationService(explanation)
    analysis = Analysis(**recovered)
    snapshot = analysis.model_dump()
    features = SafePayload(**preview["safe_payload"])
    assert service.explain(analysis, features).result.source == "fallback"
    explanation.scenario = "valid"
    assert service.explain(analysis, features).result.source == "mock"
    assert analysis.model_dump() == snapshot
    assert client.get("/api/v1/memories").json() == []


@pytest.mark.parametrize("failure", [ProviderUnavailable, ProviderTimeout])
def test_transaction_failure_then_recovery(contract, client, monkeypatch, failure, caplog):
    fraud = SpyFraudProvider()
    transactions = install(client, fraud)
    caplog.set_level(logging.INFO, logger="app.core.http")
    original = transactions.list_transactions
    original_health = transactions.health

    def fail(*args):
        raise failure("private-bank-secret")

    monkeypatch.setattr(transactions, "list_transactions", fail)
    monkeypatch.setattr(transactions, "health", fail)
    assert checked(contract, client, "get", "/api/v1/health").json()["status"] == "degraded"
    response = checked(contract, client, "post", "/api/v1/analyses", status=500,
                       json={"transaction_id": TX})
    checked(contract, client, "post", CONFIRM, "/api/v1/alerts/{alert_id}/confirmations",
            status=500, json=BODY)
    assert fraud.inputs == []
    assert client.get("/api/v1/memories").json() == []
    assert "private-bank-secret" not in response.text + caplog.text
    monkeypatch.setattr(transactions, "list_transactions", original)
    monkeypatch.setattr(transactions, "health", original_health)
    assert checked(contract, client, "get", "/api/v1/health").json()["status"] == "ok"
    checked(contract, client, "post", "/api/v1/analyses", json={"transaction_id": TX})
    checked(contract, client, "post", CONFIRM, "/api/v1/alerts/{alert_id}/confirmations", json=BODY)
    assert len(fraud.inputs) == 1


@pytest.mark.parametrize("amount", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_transaction_rejected_before_fraud_and_recovers(client, amount):
    fraud = SpyFraudProvider()
    transactions = install(client, fraud)
    original = transactions.transactions
    transactions.transactions = [tx.model_copy(update={"amount": amount}) for tx in original]
    response = client.post("/api/v1/analyses", json={"transaction_id": TX})
    assert response.status_code == 500
    assert fraud.inputs == []
    transactions.transactions = original
    assert client.post("/api/v1/analyses", json={"transaction_id": TX}).status_code == 200
    assert len(fraud.inputs) == 1


def test_rejected_requests_do_not_assess_and_next_request_recovers(contract, client):
    fraud = SpyFraudProvider()
    install(client, fraud)
    for kwargs, status in [({"content": b"x" * 16385}, 413),
                           ({"json": {"transaction_id": TX}, "headers": {"origin": "https://bad.invalid"}}, 403),
                           ({"json": {"transaction_id": TX, "secret": "private-marker"}}, 422),
                           ({"json": {"transaction_id": "missing"}}, 404)]:
        checked(contract, client, "post", "/api/v1/analyses", status=status, **kwargs)
    assert fraud.inputs == []
    checked(contract, client, "post", "/api/v1/analyses", json={"transaction_id": TX})
    assert len(fraud.inputs) == 1


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_http_confirmation_across_apps_survives_restart(tmp_path, conflicting):
    settings = Settings(_env_file=None, database_path=tmp_path / "shared.db", allow_memory_write=True)
    barrier = Barrier(2)
    with TestClient(create_app(settings)) as first, TestClient(create_app(settings)) as second:
        def submit(client, body):
            barrier.wait(timeout=5)
            return client.post(CONFIRM, json=body)
        other = {"decision": "review", "consent_to_memory": True} if conflicting else BODY
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(submit, first, BODY)
            b = pool.submit(submit, second, other)
            responses = [a.result(timeout=10), b.result(timeout=10)]
        assert sorted(r.status_code for r in responses) == ([200, 409] if conflicting else [200, 200])
        winner = next(r.json() for r in responses if r.status_code == 200)
    with TestClient(create_app(settings)) as restarted:
        replay = restarted.post(CONFIRM, json={"decision": winner["decision"], "consent_to_memory": True})
        assert replay.status_code == 200
        memories = restarted.get("/api/v1/memories").json()
        assert len(memories) == (1 if winner["decision"] == "normal" else 0)
        if memories:
            assert replay.json()["memory_id"] == memories[0]["memory_id"]


def test_memory_storage_recovery_only_writes_for_new_confirmation(client, contract, caplog):
    fraud = SpyFraudProvider(MockScenario.TIMEOUT)
    install(client, fraud)
    caplog.set_level(logging.INFO, logger="app.core.http")
    checked(contract, client, "post", "/api/v1/analyses", json={"transaction_id": TX})
    store = client.app.state.store
    with store.connect() as db:
        db.execute("""CREATE TRIGGER fail_memory BEFORE INSERT ON memories
                      BEGIN SELECT RAISE(ABORT, 'private-storage-marker'); END""")
    failed = checked(contract, client, "post", CONFIRM,
                     "/api/v1/alerts/{alert_id}/confirmations", json=BODY)
    assert failed.json()["memory_status"] == "failed"
    assert store.status(client.app.state.settings.demo_user_id, "alert_" + TX) == "normal"
    with store.connect() as db:
        db.execute("DROP TRIGGER fail_memory")
    # Recovery must not retry a historical optional write, even after another analysis.
    fraud.scenario = MockScenario.VALID
    checked(contract, client, "post", "/api/v1/analyses", json={"transaction_id": TX})
    replay = checked(contract, client, "post", CONFIRM,
                     "/api/v1/alerts/{alert_id}/confirmations", json=BODY)
    assert replay.json()["memory_status"] == "failed"
    assert client.get("/api/v1/memories").json() == []
    written = checked(contract, client, "post", "/api/v1/alerts/alert_txn_syn_004/confirmations",
                      "/api/v1/alerts/{alert_id}/confirmations", json=BODY)
    assert written.json()["memory_status"] == "written"
    assert len(client.get("/api/v1/memories").json()) == 1
    checked(contract, client, "post", CONFIRM, "/api/v1/alerts/{alert_id}/confirmations",
            status=409, json={"decision": "review", "consent_to_memory": True})
    assert "private-storage-marker" not in failed.text + replay.text + caplog.text
    assert len(fraud.inputs) == 2
