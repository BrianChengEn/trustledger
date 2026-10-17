"""Rules stay authoritative. Jev may annotate them only after a validated Backboard response."""

import httpx

from app.schemas.api import Analysis
from app.schemas.transaction import Transaction
from app.services.ai.jev_client import JevCallError, classify
from app.services.ai.privacy import safe_payload
from app.services.ai.rules import analyze


async def review(
    tx: Transaction,
    history: list[Transaction],
    request_id: str,
    prior_user_confirmation: str,
    api_key: str,
    *,
    force_live: bool = False,
    client: httpx.AsyncClient | None = None,
) -> Analysis:
    ruled = analyze(tx, history, request_id, prior_user_confirmation)
    key = api_key.strip()
    if not key or not (force_live or ruled.alert_type != "none"):
        return ruled
    payload = safe_payload(tx, history, prior_user_confirmation)
    try:
        result = await classify(payload, key, client=client)
    except JevCallError:
        return ruled.model_copy(update={"provider_mode": "degraded"})
    note = (
        f"Jev via Backboard: {result.pattern}, confidence {result.choice_confidence:.2f}. "
        "The rule result is unchanged and is not a fraud decision."
    )
    evidence = [*ruled.evidence, note] if len(ruled.evidence) < 8 else list(ruled.evidence)
    return ruled.model_copy(update={
        "provider_mode": "rules+jev-live",
        "model_version": result.model_version,
        "evidence": evidence,
        "needs_human": ruled.needs_human or result.needs_review >= 0.5,
    })
