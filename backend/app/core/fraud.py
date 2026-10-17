"""F4 internal fraud-provider boundary; no vendor wire schema or HTTP transport.

F5 may supply rules.analyze(...) and privacy.safe_payload(...) to evaluate_fraud.
Rules remain authoritative until AI-owner approval of severity/precedence mappings.
A rules confidence of 1.0 means a deterministic rule match, not fraud probability.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.schemas.api import Analysis, SafePayload
from app.services.ai.privacy import CATEGORIES


class FraudFeatures(SafePayload):
    """The same eight allowlisted fields, with closed category vocabulary."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @field_validator("merchant_category")
    @classmethod
    def controlled_category(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError("Unsupported category")
        return value


class ProviderMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    name: str
    mode: Literal["mock", "external"]
    model_version: str | None = None


class FraudAssessment(BaseModel):
    """Internal categories only; an external adapter needs an approved mapping.

    An optional finite numeric score has deliberately unknown semantics. It cannot
    supply severity, confidence, a probability, or override the deterministic rules.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    alert_type: Literal["duplicate", "amount_anomaly", "subscription_change", "none"]
    severity: Literal["low", "medium", "high"] | None
    needs_human: bool
    evidence: list[Annotated[str, Field(max_length=180)]] = Field(max_length=8)
    metadata: ProviderMetadata
    numeric_score: float | None = Field(default=None, allow_inf_nan=False)
    numeric_semantics: Literal["unknown"] = "unknown"


class FraudProvider(Protocol):
    def assess(self, features: FraudFeatures) -> FraudAssessment: ...


class FailureKind(str, Enum):
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"
    PAYMENT_REQUIRED = "payment_required"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    MALFORMED_OUTPUT = "malformed_output"
    UNSAFE_INPUT = "unsafe_input"
    UNEXPECTED = "unexpected"


class FraudProviderError(Exception):
    def __init__(self, kind: FailureKind):
        self.kind = FailureKind(kind)
        super().__init__(self.kind.value)


class FraudTimeout(FraudProviderError):
    def __init__(self):
        super().__init__(FailureKind.TIMEOUT)


class FraudUnavailable(FraudProviderError):
    def __init__(self):
        super().__init__(FailureKind.UNAVAILABLE)


class MalformedAssessment(FraudProviderError):
    def __init__(self):
        super().__init__(FailureKind.MALFORMED_OUTPUT)


class FraudHTTPError(FraudProviderError):
    """Future REST adapter translates status only, never a response body or URL."""

    def __init__(self, status_code: int):
        kinds = {401: FailureKind.UNAUTHORIZED, 402: FailureKind.PAYMENT_REQUIRED,
                 429: FailureKind.RATE_LIMITED}
        kind = kinds.get(status_code)
        if kind is None and 500 <= status_code <= 599:
            kind = FailureKind.SERVER_ERROR
        if kind is None:
            raise ValueError("Unsupported provider failure status")
        super().__init__(kind)


class UnsafeFeatures(FraudProviderError):
    def __init__(self):
        super().__init__(FailureKind.UNSAFE_INPUT)


def validated_features(features: SafePayload) -> FraudFeatures:
    try:
        # Revalidation catches mutated/model_construct instances; suppress serializer
        # warnings because they can include raw input values. Never log this payload.
        value = features.model_dump(warnings=False) if isinstance(features, SafePayload) else features
        return FraudFeatures.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        raise UnsafeFeatures() from None


def validated_assessment(value: FraudAssessment) -> FraudAssessment:
    try:
        if isinstance(value, FraudAssessment):
            value = value.model_dump(warnings=False)
        return FraudAssessment.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        raise MalformedAssessment() from None


@dataclass(frozen=True)
class FraudOutcome:
    # These are internal results; return only analysis at a future HTTP boundary.
    analysis: Analysis
    status: Literal["rules-only", "assessed", "fallback"]
    assessment: FraudAssessment | None = field(default=None, repr=False)
    failure: FailureKind | None = None


def evaluate_fraud(rules_analysis: Analysis, features: SafePayload,
                   provider: FraudProvider | None = None) -> FraudOutcome:
    """Stable rules fallback, without transaction fetching or route orchestration.

    Caller supplies the unchanged result of rules.analyze. No raw transaction,
    history, identifier, request ID or baseline analysis is passed to the provider.
    Provider exceptions/output are not logged or included in outward analysis.
    """
    baseline = Analysis.model_validate(rules_analysis.model_dump(warnings=False))
    if baseline.provider_mode != "rules-only":
        raise ValueError("A deterministic rules baseline is required")
    if provider is None:
        return FraudOutcome(baseline, "rules-only")
    try:
        payload = validated_features(features)
        assessment = validated_assessment(provider.assess(payload))
        # Do not invent rules/model precedence or advertise mock results as live.
        return FraudOutcome(baseline, "assessed", assessment=assessment)
    except FraudProviderError as exc:
        failure = exc.kind
    except TimeoutError:
        failure = FailureKind.TIMEOUT
    except ValidationError:
        failure = FailureKind.MALFORMED_OUTPUT
    except Exception:
        failure = FailureKind.UNEXPECTED
    fallback = baseline.model_copy(update={"provider_mode": "degraded"})
    return FraudOutcome(fallback, "fallback", failure=failure)


class MockScenario(str, Enum):
    VALID = "valid"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"
    PAYMENT_REQUIRED = "payment_required"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    MALFORMED = "malformed"


class MockJevProvider:
    """Fixed internal fixture, not a detector or an invented Jev REST response.

    The default result is identical for every valid input. Tests can supply another
    explicit internal assessment to exercise disagreement without score thresholds.
    """

    def __init__(self, scenario: MockScenario = MockScenario.VALID,
                 assessment: FraudAssessment | None = None):
        self.scenario = MockScenario(scenario)
        self.assessment = validated_assessment(assessment) if assessment is not None else FraudAssessment(
            alert_type="none", severity="low", needs_human=False,
            evidence=["Deterministic mock assessment; not a financial verdict."],
            metadata=ProviderMetadata(name="jev", mode="mock", model_version="mock-jev-v1"),
        )
        if self.assessment.metadata.mode != "mock":
            raise ValueError("Mock provider requires mock metadata")

    def assess(self, features: FraudFeatures) -> FraudAssessment:
        validated_features(features)
        if self.scenario == MockScenario.TIMEOUT:
            raise FraudTimeout()
        if self.scenario == MockScenario.UNAVAILABLE:
            raise FraudUnavailable()
        statuses = {MockScenario.UNAUTHORIZED: 401, MockScenario.PAYMENT_REQUIRED: 402,
                    MockScenario.RATE_LIMITED: 429, MockScenario.SERVER_ERROR: 503}
        if self.scenario in statuses:
            raise FraudHTTPError(statuses[self.scenario])
        if self.scenario == MockScenario.MALFORMED:
            # Bypass validation deliberately to test boundary validation, not a wire parser.
            return self.assessment.model_copy(update={"severity": "invalid"})
        return self.assessment.model_copy(deep=True)


def select_fraud_provider(mode: str = "rules-only") -> FraudProvider | None:
    """Explicit local selection only; no environment keys enable a live client."""
    if mode == "rules-only":
        return None
    if mode == "mock-jev":
        return MockJevProvider()
    raise ValueError("Unsupported fraud provider mode")
