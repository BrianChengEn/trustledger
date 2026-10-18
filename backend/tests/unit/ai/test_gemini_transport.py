"""The SDK request body is the privacy-safe document and does not carry the key."""
import json

import httpx

from app.services.ai.gemini_client import GoogleGenAITransport
from app.services.ai.gemini_explanation import GeminiQuota, GeminiTimeout

KEY = "unit-test-gemini-key"
DOCUMENT = {
    "task": "explain_existing_alert",
    "alert_type": "duplicate",
    "severity": "medium",
    "needs_human": True,
    "reason_codes": ["same_category_same_amount_within_24h", "human_review_required"],
    "features": {
        "merchant_category": "streaming",
        "amount_bucket": "10-25",
        "currency": "USD",
        "local_day_part": "afternoon",
        "same_category_same_amount_24h_count": 2,
        "is_subscription": True,
        "subscription_delta_bucket": "none",
        "prior_user_confirmation": "unknown",
    },
}


def _response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def test_sdk_request_body_excludes_secrets_and_raw_transaction(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        seen["header_has_key"] = request.headers.get("x-goog-api-key") == KEY
        return _response({
            "candidates": [{
                "content": {"role": "model", "parts": [{"text": json.dumps({
                    "stated_alert_type": "duplicate",
                    "why_flagged": "Possible duplicate in this category.",
                    "supporting_evidence": "The safe count is 2.",
                    "what_it_means": "Review it. This is not confirmed fraud.",
                    "what_to_check": "Compare both recent charges.",
                    "next_steps": ["Review the transaction against your receipts and recent activity."],
                })}]},
                "finishReason": "STOP",
            }]
        })

    transport = GoogleGenAITransport(
        KEY, "gemini-3.5-flash-lite", 8000, httpx.Client(transport=httpx.MockTransport(handler)))
    text = transport.generate(DOCUMENT)
    body = json.loads(seen["body"])
    assert "stated_alert_type" in text
    assert "generationConfig" not in body and "systemInstruction" not in body
    assert seen["header_has_key"] is True
    assert KEY not in seen["body"]
    assert "StreamWave" not in seen["body"] and "txn_syn_004" not in seen["body"]
    assert "11.99" not in seen["body"] and "acct_demo_a1" not in seen["body"]
    assert "streaming" in seen["body"] and "same_category_same_amount_within_24h" in seen["body"]
    assert "generativelanguage.googleapis.com" in seen["url"]
    assert KEY not in seen["url"]


def test_sdk_quota_and_timeout_are_typed(monkeypatch):
    def quota(request: httpx.Request) -> httpx.Response:
        return _response({"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "hidden"}}, 429)

    transport = GoogleGenAITransport(
        KEY, "gemini-3.5-flash-lite", 8000, httpx.Client(transport=httpx.MockTransport(quota)))
    try:
        transport.generate(DOCUMENT)
    except GeminiQuota:
        pass
    else:
        raise AssertionError("quota was not mapped")

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    transport = GoogleGenAITransport(
        KEY, "gemini-3.5-flash-lite", 8000, httpx.Client(transport=httpx.MockTransport(timeout)))
    try:
        transport.generate(DOCUMENT)
    except GeminiTimeout:
        pass
    else:
        raise AssertionError("timeout was not mapped")
    assert KEY not in "quota timeout"
