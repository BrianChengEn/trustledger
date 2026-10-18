import asyncio

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.core.store import ConflictingConfirmation
from app.schemas.api import (
    Alert, Analysis, AnalyzeRequest, Confirmation, ConfirmationRequest, Health,
    MemorySummary, PrivacyPreview,
)
from app.schemas.transaction import Transaction
from app.services.ai.decision import review
from app.services.ai.memory_policy import memory_sentence, prior_confirmation
from app.services.ai.privacy import privacy_preview

router = APIRouter(prefix="/api/v1")


def demo_transactions(request: Request) -> list[Transaction]:
    if not hasattr(request.state, "transactions"):
        state = request.app.state
        request.state.transactions = state.store.list_transactions(state.settings.demo_user_id)
    return request.state.transactions


def transaction(request: Request, transaction_id: str) -> Transaction:
    result = next((t for t in demo_transactions(request) if t.id == transaction_id), None)
    if result is None:
        raise HTTPException(404, "not_found")
    return result


def remembered(request: Request) -> list[str]:
    state = request.app.state
    return [item.summary for item in state.store.list_memories(state.settings.demo_user_id)]


def api_key(request: Request) -> str:
    return request.app.state.settings.backboard_api_key.get_secret_value()


def record_mode(request: Request, analyses: list[Analysis]) -> None:
    modes = {item.provider_mode for item in analyses}
    if "degraded" in modes:
        request.app.state.analysis_outcome = "degraded"
    elif "rules+jev-live" in modes:
        request.app.state.analysis_outcome = "rules+jev-live"


async def alerts(request: Request) -> list[Alert]:
    state = request.app.state
    rows = demo_transactions(request)
    summaries = remembered(request)
    key = api_key(request)

    async def one(tx: Transaction) -> Analysis:
        prior = prior_confirmation(tx.merchant_category, summaries)
        return await review(tx, rows, request.state.request_id, prior, key)

    reviewed = list(await asyncio.gather(*(one(tx) for tx in rows)))
    record_mode(request, reviewed)
    result = []
    for analysis in reviewed:
        if analysis.alert_type != "none":
            aid = "alert_" + analysis.transaction_id
            result.append(Alert(**analysis.model_dump(), alert_id=aid,
                                status=state.store.status(state.settings.demo_user_id, aid)))
    return result


@router.get("/health", response_model=Health)
def health(request: Request):
    outcome = getattr(request.app.state, "analysis_outcome", None)
    analysis_mode = outcome if outcome in {"rules+jev-live", "degraded"} else "rules-only"
    return Health(status="degraded" if analysis_mode == "degraded" else "ok",
                  data_mode="synthetic", analysis_mode=analysis_mode,
                  memory_mode="local-fallback" if request.app.state.settings.allow_memory_write else "off",
                  request_id=request.state.request_id)


@router.get("/transactions", response_model=list[Transaction])
def list_transactions(request: Request, limit: int = Query(25, ge=1, le=100)):
    return sorted(demo_transactions(request), key=lambda t: t.occurred_at, reverse=True)[:limit]


@router.post("/analyses", response_model=Analysis)
async def analyze_transaction(body: AnalyzeRequest, request: Request):
    tx = transaction(request, body.transaction_id)
    prior = prior_confirmation(tx.merchant_category, remembered(request))
    result = await review(tx, demo_transactions(request), request.state.request_id, prior,
                          api_key(request), force_live=True)
    record_mode(request, [result])
    return result


@router.get("/alerts", response_model=list[Alert])
async def list_alerts(request: Request):
    return await alerts(request)


@router.get("/privacy/preview/{transaction_id}", response_model=PrivacyPreview)
def preview(transaction_id: str, request: Request):
    tx = transaction(request, transaction_id)
    prior = prior_confirmation(tx.merchant_category, remembered(request))
    return privacy_preview(tx, demo_transactions(request), prior)


@router.post("/alerts/{alert_id}/confirmations", response_model=Confirmation)
async def confirm(alert_id: str, body: ConfirmationRequest, request: Request):
    alert = next((a for a in await alerts(request) if a.alert_id == alert_id), None)
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
