from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.core.store import ConflictingConfirmation
from app.schemas.api import (
    Alert, Analysis, AnalyzeRequest, Confirmation, ConfirmationRequest, Health,
    MemorySummary, PrivacyPreview,
)
from app.schemas.transaction import Transaction
from app.services.ai.memory_policy import memory_sentence
from app.services.ai.privacy import privacy_preview
from app.services.ai.rules import analyze

router = APIRouter(prefix="/api/v1")


def transaction(request: Request, transaction_id: str) -> Transaction:
    result = next((t for t in request.app.state.transactions if t.id == transaction_id), None)
    if result is None:
        raise HTTPException(404, "not_found")
    return result


def alerts(request: Request) -> list[Alert]:
    state = request.app.state
    result = []
    for tx in state.transactions:
        analysis = analyze(tx, state.transactions, request.state.request_id)
        if analysis.alert_type != "none":
            aid = "alert_" + tx.id
            result.append(Alert(**analysis.model_dump(), alert_id=aid,
                                status=state.store.status(state.settings.demo_user_id, aid)))
    return result


@router.get("/health", response_model=Health)
def health(request: Request):
    return Health(status="ok", data_mode="synthetic", analysis_mode="rules-only",
                  memory_mode="local-fallback" if request.app.state.settings.allow_memory_write else "off",
                  request_id=request.state.request_id)


@router.get("/transactions", response_model=list[Transaction])
def list_transactions(request: Request, limit: int = Query(25, ge=1, le=100)):
    return sorted(request.app.state.transactions, key=lambda t: t.occurred_at, reverse=True)[:limit]


@router.post("/analyses", response_model=Analysis)
def analyze_transaction(body: AnalyzeRequest, request: Request):
    tx = transaction(request, body.transaction_id)
    return analyze(tx, request.app.state.transactions, request.state.request_id)


@router.get("/alerts", response_model=list[Alert])
def list_alerts(request: Request):
    return alerts(request)


@router.get("/privacy/preview/{transaction_id}", response_model=PrivacyPreview)
def preview(transaction_id: str, request: Request):
    tx = transaction(request, transaction_id)
    return privacy_preview(tx, request.app.state.transactions)


@router.post("/alerts/{alert_id}/confirmations", response_model=Confirmation)
def confirm(alert_id: str, body: ConfirmationRequest, request: Request):
    alert = next((a for a in alerts(request) if a.alert_id == alert_id), None)
    if alert is None:
        raise HTTPException(404, "not_found")
    state = request.app.state
    sentence = memory_sentence(transaction(request, alert.transaction_id), body.decision,
                               body.consent_to_memory, state.settings.allow_memory_write)
    try:
        return state.store.confirm(state.settings.demo_user_id, alert_id, body.decision,
                                   body.consent_to_memory, sentence, request.state.request_id)
    except ConflictingConfirmation:
        raise HTTPException(409, "confirmation_conflict") from None


@router.get("/memories", response_model=list[MemorySummary])
def memories(request: Request):
    return request.app.state.store.list_memories(request.app.state.settings.demo_user_id)


@router.delete("/memories/{memory_id}", status_code=204)
def delete(memory_id: str, request: Request):
    if not request.app.state.store.delete_memory(request.app.state.settings.demo_user_id, memory_id):
        raise HTTPException(404, "not_found")
    return Response(status_code=204)
