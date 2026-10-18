import json
import warnings

import pytest
from pydantic import ValidationError

from app.adapters.synthetic import load_transactions
from app.core.fraud import (
    FailureKind, FraudAssessment, FraudFeatures, FraudHTTPError, MockJevProvider,
    MockScenario, UnsafeFeatures, evaluate_fraud, select_fraud_provider, validated_features,
)
from app.schemas.api import SafePayload
from app.services.ai.privacy import safe_payload
from app.services.ai.rules import analyze

PRIVATE = "private-synthetic-sentinel"


@pytest.fixture
def inputs():
    rows = load_transactions()
    return analyze(rows[3], rows, "local-request"), safe_payload(rows[3], rows)


def test_mock_is_deterministic_and_copies_result(inputs):
    _, payload = inputs
    provider = MockJevProvider()
    first = provider.assess(validated_features(payload))
    second = provider.assess(validated_features(payload))
    assert first == second and first is not second
    assert first.metadata.mode == "mock" and first.metadata.model_version == "mock-jev-v1"
    assert first.numeric_score is None and first.numeric_semantics == "unknown"
    first.evidence.append("changed locally")
    assert provider.assess(validated_features(payload)) == second


def test_rules_only_default_and_success_do_not_replace_rules(inputs):
    baseline, payload = inputs
    assert baseline.alert_type == "duplicate"
    disabled = evaluate_fraud(baseline, payload)
    assert disabled.analysis == baseline and disabled.status == "rules-only"
    success = evaluate_fraud(baseline, payload, MockJevProvider())
    assert success.status == "assessed" and success.failure is None
    assert success.assessment.alert_type == "none"
    assert success.analysis == baseline
    assert success.analysis.confidence == 1.0
    assert success.analysis.model_version is None
    success.analysis.evidence.append("local modification")
    assert len(baseline.evidence) == 1


@pytest.mark.parametrize("scenario,kind", [
    (MockScenario.TIMEOUT, FailureKind.TIMEOUT),
    (MockScenario.UNAVAILABLE, FailureKind.UNAVAILABLE),
    (MockScenario.UNAUTHORIZED, FailureKind.UNAUTHORIZED),
    (MockScenario.PAYMENT_REQUIRED, FailureKind.PAYMENT_REQUIRED),
    (MockScenario.RATE_LIMITED, FailureKind.RATE_LIMITED),
    (MockScenario.SERVER_ERROR, FailureKind.SERVER_ERROR),
    (MockScenario.MALFORMED, FailureKind.MALFORMED_OUTPUT),
])
def test_mock_failures_fall_back_without_changing_rules(inputs, scenario, kind):
    baseline, payload = inputs
    result = evaluate_fraud(baseline, payload, MockJevProvider(scenario))
    assert result.status == "fallback" and result.failure == kind
    assert result.assessment is None
    assert result.analysis.model_dump() == {**baseline.model_dump(), "provider_mode": "degraded"}
    assert baseline.provider_mode == "rules-only"


@pytest.mark.parametrize("status,kind", [(401, FailureKind.UNAUTHORIZED),
                                        (402, FailureKind.PAYMENT_REQUIRED),
                                        (429, FailureKind.RATE_LIMITED),
                                        (500, FailureKind.SERVER_ERROR),
                                        (502, FailureKind.SERVER_ERROR),
                                        (599, FailureKind.SERVER_ERROR)])
def test_typed_rest_failure_statuses(inputs, status, kind):
    class Provider:
        def assess(self, features):
            raise FraudHTTPError(status)
    result = evaluate_fraud(*inputs, Provider())
    assert result.failure == kind and result.analysis.provider_mode == "degraded"


@pytest.mark.parametrize("failure,kind", [(TimeoutError, FailureKind.TIMEOUT),
                                         (RuntimeError, FailureKind.UNEXPECTED),
                                         (NotImplementedError, FailureKind.UNEXPECTED)])
def test_exceptions_are_not_returned_or_logged(inputs, caplog, failure, kind):
    class Provider:
        def assess(self, features):
            raise failure(f"https://invalid.example/?key={PRIVATE}")
    result = evaluate_fraud(*inputs, Provider())
    assert result.failure == kind
    assert PRIVATE not in repr(result) + result.analysis.model_dump_json() + caplog.text
    assert "key=" not in caplog.text


@pytest.mark.parametrize("updates", [
    {"severity": 1.89}, {"alert_type": "fraud"}, {"needs_human": "yes"},
    {"evidence": ["x" * 181]}, {"evidence": ["x"] * 9},
    {"numeric_score": float("nan")}, {"numeric_score": float("inf")},
    {"numeric_semantics": "fraud_probability"}, {"unexpected": PRIVATE},
    {"metadata": {"name": "jev", "mode": "mock", "raw_body": PRIVATE}},
])
def test_malformed_outputs_rejected(inputs, updates):
    value = MockJevProvider().assessment.model_dump()
    value.update(updates)

    class Provider:
        def assess(self, features):
            return value
    result = evaluate_fraud(*inputs, Provider())
    assert result.failure == FailureKind.MALFORMED_OUTPUT
    assert result.assessment is None and PRIVATE not in result.analysis.model_dump_json()


@pytest.mark.parametrize("value", [None, [], "raw", {}])
def test_invalid_output_shapes(inputs, value):
    class Provider:
        def assess(self, features):
            return value
    assert evaluate_fraud(*inputs, Provider()).failure == FailureKind.MALFORMED_OUTPUT


def test_unknown_numeric_score_is_never_mapped(inputs):
    assessment = MockJevProvider().assessment.model_copy(update={"numeric_score": 1.89, "severity": None})
    result = evaluate_fraud(*inputs, MockJevProvider(assessment=assessment))
    assert result.assessment.numeric_score == 1.89 and result.assessment.severity is None
    assert result.analysis == inputs[0]


@pytest.mark.parametrize("updates", [
    {"merchant_category": PRIVATE}, {"raw_transaction": {"account_token": PRIVATE}},
    {"amount_bucket": PRIVATE}, {"same_category_same_amount_24h_count": PRIVATE},
    {"same_category_same_amount_24h_count": 21}, {"is_subscription": "true"},
])
def test_privacy_gate_rejects_before_provider_call(inputs, updates):
    called = []

    class Provider:
        def assess(self, features):
            called.append(features)
    value = inputs[1].model_dump()
    value.update(updates)
    result = evaluate_fraud(inputs[0], value, Provider())
    assert not called and result.failure == FailureKind.UNSAFE_INPUT
    assert result.analysis.provider_mode == "degraded"


def test_constructed_models_and_subclasses_cannot_smuggle_fields(inputs):
    class ExtraPayload(SafePayload):
        merchant_display: str
    extra = ExtraPayload(**inputs[1].model_dump(), merchant_display=PRIVATE)
    for value in [extra, inputs[1].model_copy(update={"merchant_category": PRIVATE}),
                  SafePayload.model_construct(**{**inputs[1].model_dump(), "amount_bucket": PRIVATE})]:
        with pytest.raises(UnsafeFeatures):
            validated_features(value)


def test_raw_transaction_rejected(inputs):
    with pytest.raises(UnsafeFeatures):
        validated_features(load_transactions()[0])


def test_provider_receives_only_allowlisted_features(inputs):
    seen = []

    class Spy:
        def assess(self, features):
            seen.append(features)
            return MockJevProvider().assess(features)
    evaluate_fraud(*inputs, Spy())
    assert type(seen[0]) is FraudFeatures
    assert set(seen[0].model_dump()) == set(SafePayload.model_fields)
    assert seen[0].model_dump() == inputs[1].model_dump()
    text = json.dumps(seen[0].model_dump())
    assert inputs[0].transaction_id not in text and inputs[0].request_id not in text
    with pytest.raises(ValidationError):
        seen[0].merchant_category = "other"


def test_invalid_outputs_cannot_leak_via_serializer_warnings(inputs):
    class Provider:
        def assess(self, features):
            return MockJevProvider().assessment.model_copy(update={"needs_human": PRIVATE})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = evaluate_fraud(*inputs, Provider())
    assert not caught and result.failure == FailureKind.MALFORMED_OUTPUT


def test_selector_fails_closed():
    assert select_fraud_provider() is None
    assert isinstance(select_fraud_provider("mock-jev"), MockJevProvider)
    for mode in ["live", "jev", PRIVATE]:
        with pytest.raises(ValueError, match="Unsupported fraud provider mode"):
            select_fraud_provider(mode)


def test_internal_assessment_bounds(inputs):
    value = MockJevProvider().assessment.model_dump()
    value["evidence"] = ["x" * 180] * 8
    assert len(FraudAssessment.model_validate(value).evidence) == 8
    with pytest.raises(ValueError):
        FraudHTTPError(200)
