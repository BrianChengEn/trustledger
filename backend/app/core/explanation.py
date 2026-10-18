"""Internal, offline explanation boundary. No route, persistence or risk mutation."""
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.fraud import FraudFeatures, validated_features
from app.schemas.api import Analysis, SafePayload

AlertType = Literal["duplicate", "amount_anomaly", "subscription_change", "none"]
REVIEW = "Review the transaction against your receipts and recent activity."
CONTACT = "If you do not recognize it, contact your bank through its official app or the number on your card."
PROTECT = "Do not share passwords or verification codes with anyone contacting you about this transaction."
Action = Literal[
    "Review the transaction against your receipts and recent activity.",
    "If you do not recognize it, contact your bank through its official app or the number on your card.",
    "Do not share passwords or verification codes with anyone contacting you about this transaction.",
]
SUMMARIES = {
    "duplicate": "The demo rules found a possible duplicate charge. It may have a legitimate explanation; this is not confirmed fraud.",
    "amount_anomaly": "The amount triggered a demo review rule. An unusual amount alone does not establish fraud.",
    "subscription_change": "The demo rules found an increase in a recurring charge. Check whether the plan or price changed; this is not confirmed fraud.",
    "none": "No demo rule raised an alert. This does not guarantee that the transaction is legitimate.",
}
FALLBACK = "An additional explanation is unavailable. Keep the existing assessment and review the transaction; this is not a finding of fraud."


class ExplanationRequest(BaseModel):
    """A closed projection of authoritative Analysis plus the existing safe snapshot."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    features: FraudFeatures
    alert_type: AlertType
    severity: Literal["low", "medium", "high"]
    needs_human: bool


class ExplanationResult(BaseModel):
    """Reviewed template text only until generated-prose policy is approved."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    summary: str = Field(min_length=1, max_length=400)
    reason_labels: tuple[AlertType, ...] = Field(max_length=1)
    recommended_actions: tuple[Action, ...] = Field(min_length=1, max_length=3)
    source: Literal["mock", "fallback"]

    @field_validator("summary")
    @classmethod
    def reviewed_plain_text(cls, value: str) -> str:
        # Reject, rather than attempt to redact, arbitrary provider text/markup/PII.
        # This is intentionally a template boundary, not a general prose sanitizer.
        if value not in (*SUMMARIES.values(), FALLBACK):
            raise ValueError("Explanation must use reviewed plain text")
        return value


class ExplanationProvider(Protocol):
    def explain(self, request: ExplanationRequest) -> ExplanationResult: ...


class ExplanationUnavailable(Exception):
    pass


class ExplanationTimeout(TimeoutError):
    pass


@dataclass(frozen=True)
class ExplanationOutcome:
    result: ExplanationResult
    failure: Literal["invalid_input", "timeout", "unavailable", "invalid_output", "provider_error"] | None = None


def request_for(analysis: Analysis, features: SafePayload) -> ExplanationRequest:
    # Validate the local analysis without passing IDs, raw evidence text, confidence,
    # model names or request IDs downstream. F4 numeric scores remain uninterpreted.
    baseline = Analysis.model_validate(analysis.model_dump(warnings=False))
    return ExplanationRequest(features=validated_features(features), alert_type=baseline.alert_type,
                              severity=baseline.severity, needs_human=baseline.needs_human)


def validated_request(request: ExplanationRequest) -> ExplanationRequest:
    value = request.model_dump(warnings=False) if isinstance(request, ExplanationRequest) else request
    # Dump/rebuild validates nested model_construct and mutated/subclass values too.
    return ExplanationRequest.model_validate(value)


def fallback_result() -> ExplanationResult:
    return ExplanationResult(summary=FALLBACK, reason_labels=(),
                             recommended_actions=(REVIEW, CONTACT, PROTECT), source="fallback")


class ExplanationService:
    def __init__(self, provider: ExplanationProvider | None = None):
        self.provider = provider

    def explain(self, analysis: Analysis, features: SafePayload) -> ExplanationOutcome:
        try:
            request = request_for(analysis, features)
        except Exception:
            # Bad inputs never reach a provider or appear in errors/logs.
            return ExplanationOutcome(fallback_result(), "invalid_input")
        if self.provider is None:
            return ExplanationOutcome(fallback_result(), "unavailable")
        try:
            # The provider gets a new immutable projection, never the analysis itself.
            value = self.provider.explain(validated_request(request))
            if isinstance(value, ExplanationResult):
                value = value.model_dump(warnings=False)
            result = ExplanationResult.model_validate(value)
            # Even approved text cannot explain a different authoritative finding.
            if (result.source != "mock" or result.reason_labels != (request.alert_type,)
                    or result.summary != SUMMARIES[request.alert_type]):
                return ExplanationOutcome(fallback_result(), "invalid_output")
            return ExplanationOutcome(result)
        except TimeoutError:
            failure = "timeout"
        except ExplanationUnavailable:
            failure = "unavailable"
        except ValidationError:
            failure = "invalid_output"
        except Exception:
            failure = "provider_error"
        return ExplanationOutcome(fallback_result(), failure)


class MockExplanationProvider:
    """Deterministic reviewed explanations; not a Gemini client or a risk model."""

    def __init__(self, scenario: Literal["valid", "timeout", "unavailable", "invalid"] = "valid"):
        if scenario not in {"valid", "timeout", "unavailable", "invalid"}:
            raise ValueError("Unsupported explanation mock scenario")
        self.scenario = scenario

    def explain(self, request: ExplanationRequest) -> ExplanationResult:
        request = validated_request(request)
        if self.scenario == "timeout":
            raise ExplanationTimeout()
        if self.scenario == "unavailable":
            raise ExplanationUnavailable()
        result = ExplanationResult(summary=SUMMARIES[request.alert_type],
                                   reason_labels=(request.alert_type,),
                                   recommended_actions=(REVIEW, CONTACT, PROTECT), source="mock")
        if self.scenario == "invalid":
            return result.model_copy(update={"summary": "Unreviewed provider output"})
        return result
