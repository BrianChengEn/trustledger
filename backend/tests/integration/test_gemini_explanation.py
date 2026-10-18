"""Gemini explanation route. Network stays disabled; the provider is injected."""
import json

import pytest
from pydantic import SecretStr

from app.api.dependencies import get_fraud_provider
from app.schemas.api import SafePayload
from app.services.ai.gemini_explanation import (
    GeminiQuota, GeminiRateLimit, GeminiTimeout, explanation_document, request_for,
)
from app.core.rules import analyze
from app.core.features import safe_payload
from app.adapters.synthetic import load_transactions

SECRET = "unit-test-gemini-key"
MERCHANTS = ("Campus Coffee", "Fresh Basket", "StreamWave", "Tech Harbor", "Metro Ride", "FitFlow")
CASES = {
    "txn_syn_004": "duplicate",
    "txn_syn_005": "amount_anomaly",
    "txn_syn_008": "subscription_change",
    "txn_syn_001": "none",
}


class Echo:
    def __init__(self, raw=None, error=None):
        self.raw = raw
        self.error = error
        self.seen = []

    def generate(self, document):
        self.seen.append(json.dumps(document, sort_keys=True))
        if self.error is not None:
            raise self.error
        if self.raw is not None:
            return self.raw
        alert = document["alert_type"]
        return json.dumps({
            "stated_alert_type": alert,
            "why_flagged": f"The rules flagged this as {alert.replace('_', ' ')}. This is not confirmed fraud.",
            "supporting_evidence": "The shared reason codes and privacy-safe features are the only evidence used.",
            "what_it_means": "This warning asks you to review the charge. It is not a fraud probability.",
            "what_to_check": "Compare the charge with your receipts and recent activity.",
            "next_steps": [
                "Review the transaction against your receipts and recent activity.",
                "Contact your bank through its official app if you do not recognize it.",
            ],
        })


def enable(client, transport):
    client.app.state.settings.gemini_api_key = SecretStr(SECRET)
    client.app.state.settings.gemini_model = "gemini-3.5-flash-lite"
    client.app.state.explanation_transport = transport


def decision(alert):
    return {key: alert[key] for key in (
        "transaction_id", "alert_type", "severity", "needs_human", "evidence",
        "provider_mode", "confidence", "status", "alert_id")}


def test_route_explains_representative_transactions_without_changing_decisions(client):
    transport = Echo()
    enable(client, transport)
    before_alerts = [decision(row) for row in client.get("/api/v1/alerts").json()]
    before_memory = client.get("/api/v1/memories").json()
    for transaction_id, alert_type in CASES.items():
        response = client.post(f"/api/v1/transactions/{transaction_id}/explanation")
        assert response.status_code == 200
        body = response.json()
        assert body["alert_type"] == alert_type
        assert body["explanation_mode"] == "gemini-live"
        assert body["model_version"] == "gemini-3.5-flash-lite"
        assert body["failure"] is None and body["sent_to_provider"] is True and body["from_cache"] is False
        assert body["safe_payload"] == body["shared"]["features"]
        assert set(body["safe_payload"]) == set(SafePayload.model_fields)
        assert alert_type.replace("_", " ") in body["why_flagged"]
        assert "provider_mode" not in body and "confidence" not in body
        assert SECRET not in response.text
        for merchant in MERCHANTS:
            assert merchant not in response.text
        assert transaction_id not in json.dumps(body["shared"])
    assert [decision(row) for row in client.get("/api/v1/alerts").json()] == before_alerts
    assert client.get("/api/v1/memories").json() == before_memory
    assert client.get("/api/v1/health").json()["analysis_mode"] == "rules-only"
    assert len(transport.seen) == len(CASES)


def test_outbound_document_is_privacy_safe(client):
    rows = load_transactions()
    transport = Echo()
    enable(client, transport)
    response = client.post("/api/v1/transactions/txn_syn_005/explanation")
    document = json.loads(transport.seen[0])
    assert set(document) == {"alert_type", "features", "needs_human", "reason_codes", "severity", "task"}
    assert set(document["features"]) == set(SafePayload.model_fields)
    assert document["alert_type"] == "amount_anomaly"
    assert "amount_bucket_at_or_above_demo_threshold" in document["reason_codes"]
    blob = transport.seen[0]
    tx = next(row for row in rows if row.id == "txn_syn_005")
    for secret in (tx.id, tx.account_token, tx.merchant_display, "849", tx.occurred_at.isoformat(), SECRET):
        assert secret not in blob
    assert response.json()["shared"] == document


def test_missing_key_uses_template_and_does_not_call_provider(client):
    transport = Echo()
    client.app.state.explanation_transport = transport
    response = client.post("/api/v1/transactions/txn_syn_004/explanation")
    body = response.json()
    assert response.status_code == 200
    assert body["explanation_mode"] == "template"
    assert body["failure"] is None and body["sent_to_provider"] is False
    assert body["model_version"] is None and body["from_cache"] is False
    assert "possible-duplicate" in body["why_flagged"]
    assert "Gemini" not in body["why_flagged"]
    assert transport.seen == []


@pytest.mark.parametrize("error,failure", [
    (GeminiQuota(), "quota"),
    (GeminiTimeout(), "timeout"),
    (GeminiRateLimit(), "rate_limited"),
])
def test_provider_failures_fall_back_without_claiming_gemini(client, error, failure):
    enable(client, Echo(error=error))
    body = client.post("/api/v1/transactions/txn_syn_008/explanation").json()
    assert body["explanation_mode"] == "fallback" and body["failure"] == failure
    assert body["sent_to_provider"] is True and body["model_version"] is None
    assert "subscription" in body["why_flagged"]
    assert "Gemini" not in body["why_flagged"] + body["supporting_evidence"]


@pytest.mark.parametrize("raw", [
    "not json",
    "",
    json.dumps({"stated_alert_type": "none", "why_flagged": "No demo rule flagged this.",
                "supporting_evidence": "Nothing else was supplied.",
                "what_it_means": "No warning was raised.",
                "what_to_check": "Compare it with your receipts.",
                "next_steps": ["Review the charge."]}),
    json.dumps({"stated_alert_type": "duplicate", "why_flagged": "This is confirmed fraud.",
                "supporting_evidence": "The shared summary says so.",
                "what_it_means": "Act now.", "what_to_check": "Look again.",
                "next_steps": ["Review the charge."]}),
    json.dumps({"stated_alert_type": "duplicate", "why_flagged": " ",
                "supporting_evidence": "Evidence.", "what_it_means": "Meaning.",
                "what_to_check": "Check.", "next_steps": ["Review the charge."]}),
])
def test_malformed_or_unsafe_output_is_not_labeled_live(client, raw):
    enable(client, Echo(raw=raw))
    body = client.post("/api/v1/transactions/txn_syn_004/explanation").json()
    assert body["explanation_mode"] == "fallback" and body["failure"] == "invalid_output"
    assert body["model_version"] is None
    assert "possible-duplicate" in body["why_flagged"]
    assert "confirmed fraud" not in body["why_flagged"].lower() or "not a determination" in body["why_flagged"]


def test_provider_exception_text_is_not_returned(client, caplog):
    class Boom:
        def generate(self, document):
            raise RuntimeError("https://example.invalid/?key=" + SECRET)

    enable(client, Boom())
    response = client.post("/api/v1/transactions/txn_syn_004/explanation")
    assert response.status_code == 200
    assert SECRET not in response.text and "example.invalid" not in response.text
    assert SECRET not in caplog.text
    assert response.json()["failure"] == "provider_error"
    assert response.json()["explanation_mode"] == "fallback"


def test_explanation_does_not_call_the_fraud_provider_or_relabel_analysis(client):
    called = []

    class Spy:
        def assess(self, features):
            called.append(True)
            raise AssertionError("explanation must not assess fraud")

    client.app.dependency_overrides[get_fraud_provider] = lambda: Spy()
    response = client.post("/api/v1/transactions/txn_syn_005/explanation")
    assert response.status_code == 200 and called == []
    analysis = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_005"})
    assert analysis.status_code == 200
    assert analysis.json()["provider_mode"] == "degraded"
    assert called == [True]
    again = client.post("/api/v1/transactions/txn_syn_005/explanation").json()
    assert again["explanation_mode"] == "template"
    assert "rules+jev-live" not in json.dumps(again)


def test_repeated_safe_request_is_cached_without_a_second_call(client):
    transport = Echo()
    enable(client, transport)
    first = client.post("/api/v1/transactions/txn_syn_004/explanation").json()
    second = client.post("/api/v1/transactions/txn_syn_004/explanation").json()
    assert first["explanation_mode"] == "gemini-live" and first["sent_to_provider"] is True
    assert second["from_cache"] is True and second["sent_to_provider"] is False
    assert second["explanation_mode"] == "gemini-live"
    assert second["why_flagged"] == first["why_flagged"]
    assert len(transport.seen) == 1


def test_template_matches_each_alert_and_omits_private_values(client):
    rows = {row.id: row for row in load_transactions()}
    expected = {
        "txn_syn_004": "possible-duplicate",
        "txn_syn_005": "unusual-amount",
        "txn_syn_008": "subscription",
        "txn_syn_001": "No demo rule",
    }
    for transaction_id, phrase in expected.items():
        body = client.post(f"/api/v1/transactions/{transaction_id}/explanation").json()
        tx = rows[transaction_id]
        assert body["explanation_mode"] == "template"
        assert phrase in body["why_flagged"]
        blob = json.dumps(body["shared"])
        for secret in (tx.merchant_display, tx.id, tx.account_token, f"{tx.amount:.2f}"):
            assert secret not in blob
        rules = analyze(tx, list(rows.values()), "local")
        features = safe_payload(tx, list(rows.values()))
        assert body["alert_type"] == rules.alert_type
        assert body["severity"] == rules.severity and body["needs_human"] == rules.needs_human
        assert explanation_document(request_for(rules, features))["features"] == features.model_dump()


def test_unknown_transaction_is_not_found(client):
    response = client.post("/api/v1/transactions/txn_missing/explanation")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
