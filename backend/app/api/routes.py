from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response

from app.api.dependencies import Analyses, Transactions
from app.core.store import ConflictingConfirmation
from app.schemas.api import (
    Alert, Analysis, AnalyzeRequest, Confirmation, ConfirmationRequest, Health,
    MemorySummary, PrivacyPreview,
)
from app.schemas.transaction import Transaction
from app.services.ai.memory_policy import memory_sentence

router = APIRouter(prefix="/api/v1")


def alerts(request: Request, analyses: Analyses) -> list[Alert]:
    state = request.app.state
    # GET and confirmation never invoke a fraud provider.
    result = analyses.alerts(request.state.request_id)
    for alert in result:
        alert.status = state.store.status(state.settings.demo_user_id, alert.alert_id)
    return result


@router.get("/health", response_model=Health)
def health(request: Request, transactions: Transactions):
    # Report current data readiness, not a previous request's cached AI outcome.
    # Public analysis remains rules-authoritative; failures are request-specific.
    provider_health = transactions.health()
    return Health(status=provider_health.status, data_mode=provider_health.data_mode, analysis_mode="rules-only",
                  memory_mode="local-fallback" if request.app.state.settings.allow_memory_write else "off",
                  request_id=request.state.request_id)


@router.get("/transactions", response_model=list[Transaction])
def list_transactions(transactions: Transactions, limit: int = Query(25, ge=1, le=100)):
    return transactions.list_transactions(limit)


@router.post("/analyses", response_model=Analysis)
def analyze_transaction(body: AnalyzeRequest, request: Request, analyses: Analyses):
    return analyses.analyze(body.transaction_id, request.state.request_id)


@router.get("/alerts", response_model=list[Alert])
def list_alerts(request: Request, analyses: Analyses):
    return alerts(request, analyses)


@router.get("/privacy/preview/{transaction_id}", response_model=PrivacyPreview)
def preview(transaction_id: Annotated[str, Path(min_length=1, max_length=80)],
            analyses: Analyses):
    return analyses.preview(transaction_id)


@router.post("/alerts/{alert_id}/confirmations", response_model=Confirmation)
def confirm(alert_id: Annotated[str, Path(min_length=1, max_length=80)],
            body: ConfirmationRequest, request: Request, transactions: Transactions, analyses: Analyses):
    alert = next((a for a in alerts(request, analyses) if a.alert_id == alert_id), None)
    if alert is None:
        raise HTTPException(404, "not_found")
    state = request.app.state
    sentence = memory_sentence(transactions.get_transaction(alert.transaction_id), body.decision,
                               body.consent_to_memory, state.settings.allow_memory_write)
    try:
        return state.store.confirm(state.settings.demo_user_id, alert_id, body.decision,
                                   body.consent_to_memory, sentence, request.state.request_id,
                                   memory_enabled=state.settings.allow_memory_write)
    except ConflictingConfirmation:
        raise HTTPException(409, "confirmation_conflict") from None


@router.get("/memories", response_model=list[MemorySummary])
def memories(request: Request):
    return request.app.state.store.list_memories(request.app.state.settings.demo_user_id)


@router.delete("/memories/{memory_id}", status_code=204)
def delete(memory_id: Annotated[str, Path(min_length=1, max_length=100)], request: Request):
    if not request.app.state.store.delete_memory(request.app.state.settings.demo_user_id, memory_id):
        raise HTTPException(404, "not_found")
    return Response(status_code=204)
