from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, StrictBool


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalyzeRequest(StrictModel):
    transaction_id: str = Field(min_length=1, max_length=80)


class ConfirmationRequest(StrictModel):
    decision: Literal["normal", "review"]
    consent_to_memory: StrictBool


class Health(StrictModel):
    status: Literal["ok", "degraded"]
    data_mode: Literal["synthetic", "nessie-live", "degraded"]
    analysis_mode: Literal["rules-only", "rules+jev-live", "degraded"]
    memory_mode: Literal["off", "local-fallback", "backboard-live", "degraded"]
    request_id: str


class Analysis(StrictModel):
    transaction_id: str
    alert_type: Literal["duplicate", "amount_anomaly", "subscription_change", "none"]
    severity: Literal["low", "medium", "high"]
    needs_human: bool
    confidence: float = Field(ge=0, le=1)
    evidence: list[Annotated[str, Field(max_length=180)]] = Field(max_length=8)
    provider_mode: Literal["rules-only", "rules+jev-live", "degraded"] = "rules-only"
    model_version: str | None = None
    request_id: str


class Alert(Analysis):
    alert_id: str
    status: Literal["open", "normal", "review"] = "open"


class SafePayload(StrictModel):
    merchant_category: str
    amount_bucket: Literal["0-10", "10-25", "25-50", "50-100", "100-250", "250+"]
    currency: Literal["USD"]
    local_day_part: Literal["morning", "afternoon", "evening", "overnight", "unknown"]
    same_category_same_amount_24h_count: int = Field(ge=0, le=20)
    is_subscription: bool
    subscription_delta_bucket: Literal["none", "up-to-20-percent", "over-20-percent", "unknown"]
    prior_user_confirmation: Literal["normal", "review", "unknown"] = "unknown"


class FieldAction(StrictModel):
    field: str
    action: Literal["allowed", "dropped", "tokenized", "generalized", "bucketed"]
    output: JsonValue = None
    reason: str = Field(max_length=180)


class PrivacyPreview(StrictModel):
    transaction_id: str
    destination: Literal["jev", "backboard-memory"] = "jev"
    schema_version: Literal["safe-ai-payload-v1"] = "safe-ai-payload-v1"
    inspection: list[FieldAction]
    safe_payload: SafePayload


ReasonCode = Literal[
    "duplicate_rule_matched",
    "same_category_same_amount_within_24h",
    "amount_anomaly_rule_matched",
    "amount_bucket_at_or_above_demo_threshold",
    "subscription_rule_matched",
    "subscription_increase_over_20_percent",
    "no_demo_rule_matched",
    "human_review_required",
    "human_review_not_required",
    "prior_category_confirmation_normal",
    "prior_category_confirmation_review",
    "recurring_subscription",
    "subscription_delta_over_20_percent",
    "subscription_delta_up_to_20_percent",
    "subscription_delta_none",
    "subscription_delta_unknown",
]


class SharedExplanation(StrictModel):
    """Exact document an explanation provider may receive. No raw transaction fields."""

    task: Literal["explain_existing_alert"]
    alert_type: Literal["duplicate", "amount_anomaly", "subscription_change", "none"]
    severity: Literal["low", "medium", "high"]
    needs_human: bool
    reason_codes: list[ReasonCode] = Field(min_length=1, max_length=8)
    features: SafePayload


class Explanation(StrictModel):
    transaction_id: str
    alert_type: Literal["duplicate", "amount_anomaly", "subscription_change", "none"]
    severity: Literal["low", "medium", "high"]
    needs_human: bool
    why_flagged: str = Field(min_length=1, max_length=500)
    supporting_evidence: str = Field(min_length=1, max_length=500)
    what_it_means: str = Field(min_length=1, max_length=500)
    what_to_check: str = Field(min_length=1, max_length=500)
    next_steps: list[Annotated[str, Field(min_length=1, max_length=180)]] = Field(min_length=1, max_length=3)
    explanation_mode: Literal["gemini-live", "template", "fallback"]
    model_version: str | None = None
    failure: Literal[
        "timeout", "unavailable", "quota", "rate_limited", "invalid_output", "provider_error", "invalid_input",
    ] | None = None
    safe_payload: SafePayload
    shared: SharedExplanation
    sent_to_provider: bool
    from_cache: bool


class MemorySummary(StrictModel):
    memory_id: str
    summary: str = Field(max_length=240)
    created_at: AwareDatetime
    source: Literal["backboard", "local-fallback"]


class RelevantMemory(StrictModel):
    """Read-only context for one later alert. It does not approve that alert."""

    transaction_id: str
    alert_id: str | None
    category: str = Field(max_length=40)
    alert_type: Literal["duplicate", "amount_anomaly", "subscription_change", "none"]
    severity: Literal["low", "medium", "high"]
    needs_human: bool
    evidence: list[Annotated[str, Field(max_length=180)]] = Field(max_length=8)
    memory_status: Literal["backboard-live", "local-fallback", "unavailable", "no-relevant-memory"]
    memory_id: str | None = None
    summary: str | None = Field(default=None, max_length=240)
    relevance: Literal["same-category"] | None = None
    retrieval: Literal["backboard-search", "category-filter"] | None = None
    source: Literal["backboard", "local-fallback"] | None = None
    still_requires_review: Literal[True] = True
    request_id: str


class Confirmation(StrictModel):
    alert_id: str
    decision: Literal["normal", "review"]
    memory_status: Literal["not-requested", "written", "pending", "skipped", "failed"]
    memory_id: str | None = None
    request_id: str


class ErrorDetail(StrictModel):
    code: str
    message: str
    request_id: str


class ErrorEnvelope(StrictModel):
    error: ErrorDetail
