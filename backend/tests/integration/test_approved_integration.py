"""Approved activation/memory policies, with all vendor traffic mocked."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.dependencies import get_fraud_provider
from app.core.config import Settings
from app.core.fraud import FailureKind, MockJevProvider, evaluate_fraud
from app.core.jev import BackboardJevProvider
from app.main import create_app
from app.services.ai.privacy import safe_payload
from app.services.ai.rules import analyze

TX = "txn_syn_004"
CONFIRM = f"/api/v1/alerts/alert_{TX}/confirmations"
BODY = {"decision": "normal", "consent_to_memory": True}


def reply(pattern="none", review=0.01):
    return {"status": "COMPLETED", "system_one": {
        "model": "jev-1.13.0", "answers": {
            "pattern": {"type": "choice", "choice": pattern, "confidence": 0.99},
            "needs_review": {"type": "noul", "noul": review},
        },
    }}


@pytest.mark.parametrize("configured", [False, True])
def test_explicit_activation_and_only_post_can_infer(tmp_path, monkeypatch, configured):
    calls = []

    async def classify(features, api_key, client):
        from app.services.ai.jev_client import parse_response
        calls.append(features.model_dump())
        assert api_key == "synthetic-key"
        return parse_response(reply())

    monkeypatch.setattr("app.core.jev.classify", classify)
    settings = Settings(_env_file=None, database_path=tmp_path / "activation.db",
                        backboard_api_key="synthetic-key",
                        fraud_provider="backboard-jev" if configured else "rules-only")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health").json()["analysis_mode"] == "rules-only"
        assert client.get("/api/v1/transactions").status_code == 200
        assert client.get("/api/v1/alerts").status_code == 200
        preview = client.get(f"/api/v1/privacy/preview/{TX}").json()
        assert calls == []
        result = client.post("/api/v1/analyses", json={"transaction_id": TX}).json()
        assert len(calls) == int(configured)
        assert result["provider_mode"] == ("rules+jev-live" if configured else "rules-only")
        rows = client.app.state.transactions
        baseline = analyze(next(t for t in rows if t.id == TX), rows, result["request_id"]).model_dump()
        for field in ("severity", "alert_type", "confidence", "needs_human", "evidence"):
            assert result[field] == baseline[field]
        if configured:
            assert calls == [preview["safe_payload"]]
            assert len(calls[0]) == 8
            assert TX not in json.dumps(calls)
        confirmation = client.post(CONFIRM, json=BODY).json()
        assert confirmation["memory_status"] == "written"
        assert client.get(f"/api/v1/privacy/preview/{TX}").json()["safe_payload"]["prior_user_confirmation"] == "normal"
        assert client.get("/api/v1/alerts").json()[0]["provider_mode"] == "rules-only"
        assert client.get("/api/v1/health").json()["analysis_mode"] == "rules-only"
        assert len(client.get("/api/v1/memories").json()) == 1
        assert client.delete("/api/v1/memories/" + confirmation["memory_id"]).status_code == 204
        assert len(calls) == int(configured)


@pytest.mark.parametrize("scenario,kind", [
    ("valid", None), ("timeout", FailureKind.TIMEOUT),
    ("connect", FailureKind.UNAVAILABLE), ("malformed", FailureKind.MALFORMED_OUTPUT),
    ("unhashable", FailureKind.MALFORMED_OUTPUT), ("bad-model", FailureKind.MALFORMED_OUTPUT),
    ("invalid-json", FailureKind.MALFORMED_OUTPUT),
    (401, FailureKind.UNAUTHORIZED), (403, FailureKind.UNAVAILABLE),
    (429, FailureKind.RATE_LIMITED), (503, FailureKind.SERVER_ERROR),
])
def test_real_adapter_mock_transport_failures(client, monkeypatch, scenario, kind, caplog):
    calls = []

    async def handler(request):
        calls.append(json.loads(request.content))
        assert request.headers["x-api-key"] == "synthetic-key"
        if scenario == "timeout":
            await asyncio.sleep(1)
        if scenario == "connect":
            raise httpx.ConnectError("private-marker", request=request)
        if isinstance(scenario, int):
            return httpx.Response(scenario, json={"secret": "private-marker"})
        if scenario == "invalid-json":
            return httpx.Response(200, text="private-marker")
        value = reply()
        if scenario == "malformed":
            value = {"secret": "private-marker"}
        if scenario == "unhashable":
            value["system_one"]["answers"]["pattern"]["choice"] = []
        if scenario == "bad-model":
            value["system_one"]["model"] = "private-marker key=secret"
        return httpx.Response(200, json=value)

    monkeypatch.setattr("app.core.jev.INFERENCE_TIMEOUT", 0.02 if scenario == "timeout" else 3)
    provider = BackboardJevProvider(SecretStr("synthetic-key"), httpx.MockTransport(handler))
    rows = client.app.state.transactions
    tx = next(t for t in rows if t.id == TX)
    baseline = analyze(tx, rows, "rid")
    outcome = evaluate_fraud(baseline, safe_payload(tx, rows), provider)
    assert outcome.failure == kind
    assert len(calls) == 1  # No retries, including auth/timeouts.
    assert set(calls[0]["system_one"]["state"]) == set(safe_payload(tx, rows).model_dump())
    for key in ("severity", "confidence", "needs_human", "alert_type", "evidence"):
        assert getattr(outcome.analysis, key) == getattr(baseline, key)
    assert outcome.analysis.provider_mode == ("degraded" if kind else "rules+jev-live")
    assert "private-marker" not in outcome.analysis.model_dump_json() + caplog.text
    if not kind:
        assert outcome.assessment.needs_human is None
        assert outcome.assessment.severity is None and outcome.assessment.numeric_score is None


def test_missing_key_never_opens_transport(client):
    def forbidden(request):
        pytest.fail("Missing credentials must not open a transport")
    provider = BackboardJevProvider(SecretStr(" "), httpx.MockTransport(forbidden))
    client.app.dependency_overrides[get_fraud_provider] = lambda: provider
    result = client.post("/api/v1/analyses", json={"transaction_id": TX})
    assert result.status_code == 200 and result.json()["provider_mode"] == "degraded"


def test_memory_snapshot_once_and_rules_still_run(client, monkeypatch):
    assert client.post(CONFIRM, json=BODY).json()["memory_status"] == "written"
    store = client.app.state.store
    original = store.consented_memory_summaries
    calls = []

    def read(owner):
        calls.append(owner)
        return original(owner)

    monkeypatch.setattr(store, "consented_memory_summaries", read)
    alerts = client.get("/api/v1/alerts").json()
    assert len(calls) == 1 and len(alerts) == 3
    calls.clear()
    result = client.post("/api/v1/analyses", json={"transaction_id": TX}).json()
    assert calls == [client.app.state.settings.demo_user_id]
    assert result["alert_type"] == "duplicate" and result["needs_human"]
    assert result["severity"] == "medium" and result["confidence"] == 1
    assert any("category as normal" in line for line in result["evidence"])
    # The same merchant and amount still trigger duplicate detection after consent.
    assert "Another charge" in result["evidence"][0]


@pytest.mark.parametrize("failure", [RuntimeError("private-marker"), TimeoutError("private-marker")])
def test_memory_failure_is_unknown_and_does_not_change_risk(client, monkeypatch, failure, caplog):
    before = client.post("/api/v1/analyses", json={"transaction_id": TX}).json()

    def fail(owner):
        raise failure
    monkeypatch.setattr(client.app.state.store, "consented_memory_summaries", fail)
    after = client.post("/api/v1/analyses", json={"transaction_id": TX}).json()
    assert {k: v for k, v in after.items() if k != "request_id"} == {
        k: v for k, v in before.items() if k != "request_id"}
    assert client.get(f"/api/v1/privacy/preview/{TX}").json()["safe_payload"]["prior_user_confirmation"] == "unknown"
    assert "private-marker" not in json.dumps(after) + caplog.text


def test_other_owner_and_unlinked_memories_cannot_match(client):
    store = client.app.state.store
    owner = client.app.state.settings.demo_user_id
    sentence = "The demo user explicitly confirmed a streaming alert as normal. Recheck future evidence."
    other = store.confirm("other-owner", "other-alert", "normal", True, sentence, "rid")
    # Even a sanitized memory with no successful consented confirmation is ineligible.
    with store.connect() as db:
        db.execute("INSERT INTO memories VALUES (?,?,?,?)", ("orphan", owner, sentence, "2026-10-17T00:00:00Z"))
    assert client.delete("/api/v1/memories/" + other.memory_id).status_code == 404
    assert client.get(f"/api/v1/privacy/preview/{TX}").json()["safe_payload"]["prior_user_confirmation"] == "unknown"
    # A corrupt cross-owner link cannot grant access to another owner's memory.
    with store.connect() as db:
        result = json.dumps({"memory_id": other.memory_id, "memory_status": "written"})
        db.execute("INSERT INTO confirmations VALUES (?,?,?,?,?)", (owner, "forged", "normal", 1, result))
    assert store.consented_memory_summaries(owner) == []


def test_memory_survives_jev_failure_and_failed_memory_never_matches(client, monkeypatch):
    client.app.dependency_overrides[get_fraud_provider] = lambda: MockJevProvider("unavailable")
    assert client.post(CONFIRM, json=BODY).json()["memory_status"] == "written"
    result = client.post("/api/v1/analyses", json={"transaction_id": TX}).json()
    assert result["provider_mode"] == "degraded" and result["needs_human"]
    assert any("category as normal" in line for line in result["evidence"])
    store = client.app.state.store

    def fail(*args):
        raise RuntimeError("memory unavailable")
    monkeypatch.setattr(store, "_write_memory", fail)
    response = client.post("/api/v1/alerts/alert_txn_syn_005/confirmations", json=BODY).json()
    assert response["memory_status"] == "failed"
    assert store.status(client.app.state.settings.demo_user_id, "alert_txn_syn_005") == "normal"
    assert client.get("/api/v1/privacy/preview/txn_syn_005").json()["safe_payload"]["prior_user_confirmation"] == "unknown"


@pytest.mark.parametrize("summary", [
    "The demo user explicitly confirmed a streaming alert as normal. private-marker",
    "The demo user explicitly confirmed a private-marker alert as normal. Recheck future evidence.",
])
def test_malformed_memory_does_not_enter_provider(client, summary):
    store = client.app.state.store
    store.confirm(client.app.state.settings.demo_user_id, "imported", "normal", True, summary, "rid")
    seen = []

    class Spy(MockJevProvider):
        def assess(self, features):
            seen.append(features.model_dump())
            return super().assess(features)
    client.app.dependency_overrides[get_fraud_provider] = lambda: Spy()
    assert client.post("/api/v1/analyses", json={"transaction_id": TX}).status_code == 200
    assert seen[0]["prior_user_confirmation"] == "unknown"
    assert "private-marker" not in json.dumps(seen)


def test_locked_optional_memory_falls_back_without_blocking_analysis(client):
    store = client.app.state.store
    # Separate connection holds an exclusive lock; optional context has a short wait.
    with store.connect() as db:
        db.execute("BEGIN EXCLUSIVE")
        result = client.post("/api/v1/analyses", json={"transaction_id": TX})
        assert result.status_code == 200
        assert result.json()["alert_type"] == "duplicate" and result.json()["needs_human"]
        assert not any("category as normal" in line for line in result.json()["evidence"])
