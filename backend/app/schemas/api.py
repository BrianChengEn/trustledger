from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalyzeRequest(StrictModel):
    transaction_id: str = Field(min_length=1, max_length=80)


class ConfirmationRequest(StrictModel):
    decision: Literal["normal", "review"]
    consent_to_memory: bool


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
    evidence: list[str] = Field(max_length=8)
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
    local_day_part: Literal["morning", "afternoon", "evening", "overnight"]
    same_category_same_amount_24h_count: int = Field(ge=0, le=20)
    is_subscription: bool
    subscription_delta_bucket: Literal["none", "up-to-20-percent", "over-20-percent", "unknown"]
    prior_user_confirmation: Literal["normal", "review", "unknown"] = "unknown"


class FieldAction(StrictModel):
    field: str
    action: Literal["allowed", "dropped", "tokenized", "generalized", "bucketed"]
    output: str | None = None
    reason: str = Field(max_length=180)


class PrivacyPreview(StrictModel):
    transaction_id: str
    destination: Literal["jev", "backboard-memory"] = "jev"
    schema_version: Literal["safe-ai-payload-v1"] = "safe-ai-payload-v1"
    inspection: list[FieldAction]
    safe_payload: SafePayload


class MemorySummary(StrictModel):
    memory_id: str
    summary: str = Field(max_length=240)
    created_at: datetime
    source: Literal["backboard", "local-fallback"]


class Confirmation(StrictModel):
    alert_id: str
    decision: Literal["normal", "review"]
    memory_status: Literal["not-requested", "written", "pending", "skipped", "failed"]
    memory_id: str | None = None
    request_id: str
