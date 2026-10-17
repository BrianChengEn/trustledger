"""Jev through Backboard. The direct TypeSafe API is not the selected route."""

from pydantic import BaseModel, ConfigDict, Field
import httpx

from app.schemas.api import SafePayload

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
}


class JevCallError(Exception):
    """Safe failure. The message is a code, never a response body or credential."""


class JevClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pattern: str
    needs_review: float = Field(ge=0, le=1)
    choice_confidence: float = Field(ge=0, le=1)
    model_version: str = Field(min_length=1, max_length=80)


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
        "system_one": {"state": state, "questions": QUESTIONS},
    }


def _unit(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise JevCallError("invalid_response")
    number = float(value)
    if not 0 <= number <= 1:
        raise JevCallError("invalid_response")
    return number


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
    if not isinstance(answers, dict) or not isinstance(model, str) or not model.strip():
        raise JevCallError("invalid_response")
    pattern = answers.get("pattern")
    review = answers.get("needs_review")
    if not isinstance(pattern, dict) or not isinstance(review, dict):
        raise JevCallError("invalid_response")
    if pattern.get("type") != "choice" or review.get("type") != "noul":
        raise JevCallError("invalid_response")
    choice = pattern.get("choice")
    if choice not in _PATTERNS:
        raise JevCallError("invalid_response")
    return JevClassification(
        pattern=choice,
        needs_review=_unit(review.get("noul")),
        choice_confidence=_unit(pattern.get("confidence")),
        model_version=model.strip(),
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
        try:
            parsed = response.json()
        except ValueError:
            raise JevCallError("invalid_response") from None
        return parse_response(parsed)

    if client is not None:
        return await send(client)
    async with httpx.AsyncClient(timeout=8.0) as http:
        return await send(http)
