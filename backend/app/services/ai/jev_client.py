"""Jev through Backboard. The direct TypeSafe API is not the selected route."""

from pydantic import BaseModel, ConfigDict, Field
import httpx

from app.schemas.api import SafePayload
from app.services.ai.policy import EXPECTED_JEV_MODEL

MESSAGES_URL = "https://app.backboard.io/api/threads/messages"
MODEL_NAME = "jev-latest"
_STATE_FIELDS = (
    "merchant_category",
    "amount_bucket",
    "currency",
    "local_day_part",
    "same_category_same_amount_24h_count",
    "is_subscription",
    "subscription_delta_bucket",
    "prior_user_confirmation",
)
_PATTERNS = {"duplicate", "amount_anomaly", "subscription_change", "none"}
QUESTIONS = {
    "pattern": {
        "type": "choice",
        "instructions": (
            "Which review pattern matches the minimized features in state? "
            "Choose none when none of the patterns apply."
        ),
        "criteria": {
            "duplicate": "Same category and amount counted more than once in a day",
            "amount_anomaly": "Amount bucket is 250+",
            "subscription_change": "Subscription delta bucket is over-20-percent",
            "none": "No listed pattern applies",
        },
    },
    "needs_review": {
        "type": "noul",
        "instructions": "Should a person review this minimized record before treating it as routine?",
        "criteria": {
            "true": "A person should look at the evidence",
            "false": "The minimized record looks routine",
        },
    },
    "severity": {
        "type": "score",
        "instructions": "Score the urgency for human review without authorizing any action.",
        "criteria": ["Low", "Medium", "High"],
    },
}


class JevCallError(Exception):
    """Safe failure. The message is a code, never a response body or credential."""


class JevClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pattern: str
    needs_review: float = Field(ge=0, le=1)
    choice_confidence: float = Field(ge=0, le=1)
    model_version: str = Field(min_length=1, max_length=80)
    severity_score: float = Field(default=0, ge=0, le=2)


def request_body(payload: SafePayload) -> dict:
    """Backboard System One body. state is the allowlisted payload and nothing else."""
    state = payload.model_dump(mode="json")
    if set(state) != set(_STATE_FIELDS):
        raise JevCallError("unsafe_state")
    return {
        "content": "Classify the minimized features in system_one.state.",
        "llm_provider": "typesafe",
        "model_name": MODEL_NAME,
        "stream": False,
        "memory": "off",
        "system_one": {"state": state, "questions": QUESTIONS},
    }


def _unit(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise JevCallError("invalid_response")
    if not 0 <= value <= 1:
        raise JevCallError("invalid_response")
    return float(value)


def parse_response(data: object) -> JevClassification:
    if not isinstance(data, dict):
        raise JevCallError("invalid_response")
    status = data.get("status")
    if status is not None and status != "COMPLETED":
        raise JevCallError("incomplete_response")
    system = data.get("system_one")
    if not isinstance(system, dict):
        raise JevCallError("invalid_response")
    answers = system.get("answers")
    model = system.get("model")
    if (not isinstance(answers, dict) or not isinstance(model, str)
            or model.strip() != EXPECTED_JEV_MODEL):
        raise JevCallError("invalid_response")
    pattern = answers.get("pattern")
    review = answers.get("needs_review")
    if not isinstance(pattern, dict) or not isinstance(review, dict):
        raise JevCallError("invalid_response")
    if pattern.get("type") != "choice" or review.get("type") != "noul":
        raise JevCallError("invalid_response")
    choice = pattern.get("choice")
    if not isinstance(choice, str) or choice not in _PATTERNS:
        raise JevCallError("invalid_response")
    severity = answers.get("severity")
    if (not isinstance(severity, dict) or severity.get("type") != "score"
            or severity.get("legend") != {"0": "Low", "1": "Medium", "2": "High"}):
        raise JevCallError("invalid_response")
    score = severity.get("score")
    if isinstance(score, bool) or not isinstance(score, int | float) or not 0 <= score <= 2:
        raise JevCallError("invalid_response")
    return JevClassification(
        pattern=choice,
        needs_review=_unit(review.get("noul")),
        choice_confidence=_unit(pattern.get("confidence")),
        model_version=model.strip(),
        severity_score=float(score),
    )


async def classify(
    payload: SafePayload,
    api_key: str,
    client: httpx.AsyncClient | None = None,
) -> JevClassification:
    key = api_key.strip()
    if not key:
        raise JevCallError("missing_key")
    body = request_body(payload)
    headers = {"X-API-Key": key, "Content-Type": "application/json"}

    async def send(http: httpx.AsyncClient) -> JevClassification:
        try:
            response = await http.post(MESSAGES_URL, headers=headers, json=body)
        except httpx.HTTPError:
            raise JevCallError("request_failed") from None
        if response.status_code != 200:
            raise JevCallError("request_failed")
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type != "application/json" and not content_type.endswith("+json"):
            raise JevCallError("invalid_response")
        try:
            parsed = response.json()
        except ValueError:
            raise JevCallError("invalid_response") from None
        return parse_response(parsed)

    if client is not None:
        return await send(client)
    async with httpx.AsyncClient(timeout=5.0) as http:
        return await send(http)
