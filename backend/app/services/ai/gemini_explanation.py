"""Gemini explains an existing alert. It cannot change the fraud decision.

The outbound document is the eight-field safe payload plus closed reason codes.
Templates stay available when Gemini is not configured or a call fails.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from typing import Literal, Protocol

from pydantic import ValidationError

from app.core.explanation import CONTACT, PROTECT, REVIEW, ExplanationRequest, request_for
from app.schemas.api import Analysis, Explanation, ReasonCode, SafePayload, SharedExplanation
from app.services.ai.privacy import CATEGORIES

Failure = Literal[
    "timeout", "unavailable", "quota", "rate_limited", "invalid_output", "provider_error", "invalid_input",
]
Mode = Literal["gemini-live", "template", "fallback"]

PRIMARY: dict[str, ReasonCode] = {
    "duplicate": "duplicate_rule_matched",
    "amount_anomaly": "amount_anomaly_rule_matched",
    "subscription_change": "subscription_rule_matched",
    "none": "no_demo_rule_matched",
}
SPECIFIC: dict[str, ReasonCode] = {
    "duplicate": "same_category_same_amount_within_24h",
    "amount_anomaly": "amount_bucket_at_or_above_demo_threshold",
    "subscription_change": "subscription_increase_over_20_percent",
}
DELTA: dict[str, ReasonCode] = {
    "over-20-percent": "subscription_delta_over_20_percent",
    "up-to-20-percent": "subscription_delta_up_to_20_percent",
    "none": "subscription_delta_none",
    "unknown": "subscription_delta_unknown",
}
WHY = {
    "duplicate": (
        "The rules raised a possible-duplicate warning for this category and amount band. "
        "Two similar charges close together can be a mistake, a retry, or something you meant to buy. "
        "This is not a determination of fraud."
    ),
    "amount_anomaly": (
        "The rules raised an unusual-amount warning because the amount falls in the highest demo band. "
        "That is a reason to look twice. It is not proof of fraud and it is not a fraud probability."
    ),
    "subscription_change": (
        "The rules raised a subscription warning because a recurring charge increased by more than 20 percent. "
        "The price may have changed, or the charge may be unexpected. This is not a determination of fraud."
    ),
    "none": (
        "No demo rule raised an alert from the available evidence. Some checks may not apply or may lack required "
        "evidence. An absent alert does not prove the transaction is legitimate."
    ),
}
MEANS = {
    "duplicate": "The warning means the pattern matched the duplicate rule. TrustLedger does not know whether both charges were intentional.",
    "amount_anomaly": "The warning means the amount band is high for this demo. It does not say the purchase was unauthorized.",
    "subscription_change": "The warning means the recurring price band went up. TrustLedger cannot see a plan name or a bill.",
    "none": "No warning was raised. You can still compare the charge with your receipts. Absence of an alert is not a guarantee.",
}
CHECK = {
    "duplicate": "Check whether you recognize both recent charges in this category, including receipts from the last day.",
    "amount_anomaly": "Check whether you recognize a purchase in this category and amount band.",
    "subscription_change": "Check whether you agreed to a higher recurring price in this category.",
    "none": "If something still looks unfamiliar, compare the charge with your receipts and recent activity.",
}
STEPS = (REVIEW, CONTACT, PROTECT)
UNSAFE = re.compile(
    r"definitely fraudulent|(?<!not )confirmed fraud|(?<!not )this is fraud|fraudulent charge|"
    r"\d+\s*%|\b(?:we|i) (?:blocked|froze|transferred|reversed|cancelled)\b|"
    r"send (?:me |us )?(?:your )?password|share your password|"
    r"api[_ ]?key|<\s*/?\s*[a-z]|https?://",
    re.I,
)
CARD = re.compile(r"(?:\d[ -]?){13,19}")


class GeminiTimeout(Exception):
    pass


class GeminiUnavailable(Exception):
    pass


class GeminiQuota(Exception):
    pass


class GeminiRateLimit(Exception):
    pass


class GeminiProviderError(Exception):
    pass


class InvalidExplanation(Exception):
    pass


class ExplanationTransport(Protocol):
    def generate(self, document: dict) -> str: ...


class ExplanationCache:
    def __init__(self, limit: int = 32):
        self.limit = limit
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            value = self._items.get(key)
            return None if value is None else dict(value)

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            if key not in self._items and len(self._items) >= self.limit:
                self._items.pop(next(iter(self._items)))
            self._items[key] = dict(value)


def reason_codes(request: ExplanationRequest) -> tuple[ReasonCode, ...]:
    features = request.features
    specific = SPECIFIC.get(request.alert_type)
    supported = (
        request.alert_type == "duplicate" and features.same_category_same_amount_24h_count >= 2
        or request.alert_type == "amount_anomaly" and features.amount_bucket == "250+"
        or request.alert_type == "subscription_change" and features.subscription_delta_bucket == "over-20-percent"
    )
    codes: list[ReasonCode] = [specific if specific and supported else PRIMARY[request.alert_type]]
    codes.append("human_review_required" if request.needs_human else "human_review_not_required")
    if features.prior_user_confirmation == "normal":
        codes.append("prior_category_confirmation_normal")
    elif features.prior_user_confirmation == "review":
        codes.append("prior_category_confirmation_review")
    if features.is_subscription:
        codes.append("recurring_subscription")
        codes.append(DELTA[features.subscription_delta_bucket])
    return tuple(codes)


def explanation_document(request: ExplanationRequest) -> dict:
    """The only object a provider may receive. No identifiers and no raw evidence."""
    document = {
        "task": "explain_existing_alert",
        "alert_type": request.alert_type,
        "severity": request.severity,
        "needs_human": request.needs_human,
        "reason_codes": list(reason_codes(request)),
        "features": request.features.model_dump(mode="json"),
    }
    # Rebuild through the public schema so a future field cannot slip out unreviewed.
    return SharedExplanation.model_validate(document).model_dump(mode="json")


def _facts(document: dict) -> str:
    features = document["features"]
    recurring = "yes" if features["is_subscription"] else "no"
    text = (
        f"Category {features['merchant_category']}. Amount band {features['amount_bucket']}. "
        f"Time of day {features['local_day_part']}. Same category and amount band in 24 hours: "
        f"{features['same_category_same_amount_24h_count']}. Recurring flag: {recurring}. "
        f"Subscription change band: {features['subscription_delta_bucket']}. "
        f"Prior confirmation: {features['prior_user_confirmation']}. "
        "No merchant name, exact amount, account number, or identifier was used."
    )
    if "prior_category_confirmation_normal" in document["reason_codes"]:
        text += " A saved preference says this category was normal before. The alert is still shown."
    if len(text) > 500:
        raise InvalidExplanation()
    return text


def template_prose(document: dict) -> dict:
    alert = document["alert_type"]
    return {
        "why_flagged": WHY[alert],
        "supporting_evidence": _facts(document),
        "what_it_means": MEANS[alert],
        "what_to_check": CHECK[alert],
        "next_steps": list(STEPS),
    }


def _reject(text: str, forbidden: tuple[str, ...]) -> None:
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        raise InvalidExplanation()
    if UNSAFE.search(text) or CARD.search(text):
        raise InvalidExplanation()
    folded = text.casefold()
    for marker in forbidden:
        if marker and marker.casefold() in folded:
            raise InvalidExplanation()


def validate_prose(raw: str, alert_type: str, forbidden: tuple[str, ...]) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        raise InvalidExplanation() from None
    if not isinstance(value, dict) or value.get("stated_alert_type") != alert_type:
        raise InvalidExplanation()
    steps = value.get("next_steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 3:
        raise InvalidExplanation()
    prose = {
        "why_flagged": value.get("why_flagged"),
        "supporting_evidence": value.get("supporting_evidence"),
        "what_it_means": value.get("what_it_means"),
        "what_to_check": value.get("what_to_check"),
    }
    for item in prose.values():
        _reject(item, forbidden)
    for step in steps:
        if not isinstance(step, str) or not step.strip() or len(step) > 180:
            raise InvalidExplanation()
        _reject(step, forbidden)
    prose["next_steps"] = steps
    return prose


def _document_is_safe(document: dict, forbidden: tuple[str, ...]) -> bool:
    blob = json.dumps(document, sort_keys=True).casefold()
    return all(not marker or marker.casefold() not in blob for marker in forbidden)


def _cache_key(model: str, document: dict) -> str:
    body = json.dumps({"model": model, "document": document}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


class GeminiExplanationService:
    def __init__(self, transport: ExplanationTransport | None = None, *, configured: bool = False,
                 model: str | None = None, cache: ExplanationCache | None = None):
        self.transport = transport
        self.configured = configured
        self.model = model
        self.cache = cache or ExplanationCache()

    def explain(self, analysis: Analysis, features: SafePayload,
                forbidden: tuple[str, ...] = ()) -> Explanation:
        before = analysis.model_dump_json()
        safe_features = _coerce_features(features)
        try:
            request = request_for(analysis, safe_features)
            document = explanation_document(request)
        except (ValidationError, InvalidExplanation, ValueError, TypeError):
            return self._fallback_input(analysis, safe_features)
        if analysis.model_dump_json() != before:
            analysis = Analysis.model_validate_json(before)
        if not _document_is_safe(document, forbidden):
            return self._view(analysis, safe_features, template_prose(document), "fallback", "invalid_input",
                              False, False, None, document)
        if not self.configured:
            return self._view(analysis, safe_features, template_prose(document), "template", None,
                              False, False, None, document)
        cached = self.cache.get(_cache_key(self.model or "", document))
        if cached is not None:
            return self._view(analysis, safe_features, cached, "gemini-live", None, False, True,
                              self.model, document)
        if self.transport is None:
            return self._view(analysis, safe_features, template_prose(document), "fallback", "unavailable",
                              False, False, None, document)
        try:
            prose = validate_prose(self.transport.generate(document), request.alert_type, forbidden)
        except GeminiTimeout:
            failure: Failure = "timeout"
        except GeminiUnavailable:
            failure = "unavailable"
        except GeminiQuota:
            failure = "quota"
        except GeminiRateLimit:
            failure = "rate_limited"
        except InvalidExplanation:
            failure = "invalid_output"
        except Exception:
            failure = "provider_error"
        else:
            self.cache.put(_cache_key(self.model or "", document), prose)
            return self._view(analysis, safe_features, prose, "gemini-live", None, True, False,
                              self.model, document)
        if analysis.model_dump_json() != before:
            analysis = Analysis.model_validate_json(before)
        return self._view(analysis, safe_features, template_prose(document), "fallback", failure,
                          True, False, None, document)

    def _fallback_input(self, analysis: Analysis, features: SafePayload) -> Explanation:
        blank = {
            "task": "explain_existing_alert",
            "alert_type": analysis.alert_type,
            "severity": analysis.severity,
            "needs_human": analysis.needs_human,
            "reason_codes": ["no_demo_rule_matched" if analysis.alert_type == "none" else PRIMARY[analysis.alert_type]],
            "features": features.model_dump(mode="json"),
        }
        return self._view(analysis, features, template_prose(blank), "fallback", "invalid_input",
                          False, False, None, blank)

    def _view(self, analysis: Analysis, features: SafePayload, prose: dict, mode: Mode,
              failure: Failure | None, sent: bool, from_cache: bool, model: str | None,
              document: dict) -> Explanation:
        shared = document
        return Explanation(
            transaction_id=analysis.transaction_id,
            alert_type=analysis.alert_type,
            severity=analysis.severity,
            needs_human=analysis.needs_human,
            why_flagged=prose["why_flagged"],
            supporting_evidence=prose["supporting_evidence"],
            what_it_means=prose["what_it_means"],
            what_to_check=prose["what_to_check"],
            next_steps=prose["next_steps"],
            explanation_mode=mode,
            model_version=model if mode == "gemini-live" else None,
            failure=failure,
            safe_payload=features,
            shared=SharedExplanation.model_validate(shared),
            sent_to_provider=sent,
            from_cache=from_cache,
        )


def _coerce_features(features: SafePayload) -> SafePayload:
    data = features.model_dump(mode="json")
    if data.get("merchant_category") not in CATEGORIES:
        data["merchant_category"] = "other"
    return SafePayload.model_validate(data)
