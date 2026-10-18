"""Server-side Gemini transport. The API key never leaves this process."""
from __future__ import annotations

import json

import httpx

from app.services.ai.gemini_explanation import (
    GeminiProviderError, GeminiQuota, GeminiRateLimit, GeminiTimeout, GeminiUnavailable, InvalidExplanation,
)

SYSTEM = (
    "You explain an existing TrustLedger alert for someone who is not a fraud analyst. "
    "You do not decide whether the transaction is fraudulent, and you do not change the alert. "
    "Use only the JSON object in the user message. Do not invent merchant names, account activity, "
    "amounts, probabilities, customer behavior, bank actions, or evidence that is not in that JSON. "
    "If a point is not supported, say the shared summary does not include it. "
    "Never say the transaction is definitely fraudulent or confirmed fraud. "
    "Return one JSON object with stated_alert_type copied exactly from alert_type, plus why_flagged, "
    "supporting_evidence, what_it_means, what_to_check, and next_steps (1 to 3 short plain-text steps). "
    "No markdown, HTML, links, or identifiers."
)


def _failure(code: int | None, status: str):
    label = status.upper()
    if code in {401, 403} or label in {"UNAUTHENTICATED", "PERMISSION_DENIED"}:
        return GeminiUnavailable()
    if code == 402 or "QUOTA" in label or label in {"RESOURCE_EXHAUSTED", "BILLING_DISABLED"}:
        return GeminiQuota()
    if code == 429 or label == "RATE_LIMIT_EXCEEDED":
        return GeminiRateLimit()
    if code == 408 or "TIMEOUT" in label:
        return GeminiTimeout()
    return GeminiProviderError()


class GoogleGenAITransport:
    """One generateContent call, no retries, using the pinned google-genai SDK."""

    def __init__(self, api_key: str, model: str, timeout_ms: int, httpx_client: httpx.Client | None = None):
        self.api_key = api_key
        self.model = model
        self.timeout_ms = timeout_ms
        self.httpx_client = httpx_client

    def generate(self, document: dict) -> str:
        from google import genai
        from google.genai import errors, types

        client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(
                timeout=self.timeout_ms,
                httpx_client=self.httpx_client,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        # gemini-3.5-flash-lite accepted a contents-only generateContent call.
        # A generationConfig/systemInstruction body returned HTTP 400 INVALID_ARGUMENT,
        # so the instruction stays in the user text and the SDK timeout stays client-side.
        prompt = SYSTEM + "\n\n" + json.dumps(document, sort_keys=True, separators=(",", ":"))
        try:
            response = client.models.generate_content(model=self.model, contents=prompt)
        except errors.APIError as exc:
            code = exc.code if isinstance(exc.code, int) else None
            raise _failure(code, str(exc.status or "")) from None
        except (httpx.TimeoutException, TimeoutError):
            raise GeminiTimeout() from None
        except Exception:
            raise GeminiProviderError() from None
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise InvalidExplanation()
        return text
