import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.core.store import ConflictingConfirmation
from app.schemas.api import (
    Alert, Analysis, AnalyzeRequest, Confirmation, ConfirmationRequest, Health,
    MemorySummary, PrivacyPreview,
)
from app.schemas.transaction import Transaction
from app.services.ai.backboard_client import MemoryCallError, delete_memory
from app.services.ai.decision import review
from app.services.ai.memory_policy import memory_sentence, prior_confirmation
from app.services.ai.memory_sync import consented_summaries, remove_remote_memory, write_consented_memory
from app.services.ai.privacy import privacy_preview

router = APIRouter(prefix="/api/v1")


def transaction(request: Request, transaction_id: str) -> Transaction:
    result = next((t for t in request.app.state.transactions if t.id == transaction_id), None)
    if result is None:
        raise HTTPException(404, "not_found")
    return result


def api_key(request: Request) -> str:
    return request.app.state.settings.backboard_api_key.get_secret_value()


@asynccontextmanager
async def vendor_http(request: Request):
    """Use a test transport when one is installed. Production opens its own client."""
    client = getattr(request.app.state, "backboard_client", None)
    if client is not None:
        yield client
        return
    transport = getattr(request.app.state, "backboard_transport", None)
    if transport is None:
        yield None
        return
    async with httpx.AsyncClient(transport=transport) as http:
        yield http


async def remembered(request: Request) -> list[str]:
    state = request.app.state
    async with vendor_http(request) as http:
        summaries, outcome = await consented_summaries(
            state.store, state.settings.demo_user_id, api_key(request), http)
    if outcome:
        state.memory_outcome = outcome
    return summaries


def record_mode(request: Request, analyses: list[Analysis]) -> None:
    modes = {item.provider_mode for item in analyses}
    if "degraded" in modes:
        request.app.state.analysis_outcome = "degraded"
    elif "rules+jev-live" in modes:
        request.app.state.analysis_outcome = "rules+jev-live"


async def alerts(request: Request) -> list[Alert]:
    state = request.app.state
    summaries = await remembered(request)
    key = api_key(request)

    async def one(tx: Transaction) -> Analysis:
        prior = prior_confirmation(tx.merchant_category, summaries)
        return await review(tx, state.transactions, request.state.request_id, prior, key)

    reviewed = list(await asyncio.gather(*(one(tx) for tx in state.transactions)))
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
    if not request.app.state.settings.allow_memory_write:
        memory_mode = "off"
    else:
        remembered_mode = getattr(request.app.state, "memory_outcome", None)
        memory_mode = (
            remembered_mode if remembered_mode in {"backboard-live", "degraded"} else "local-fallback")
    return Health(status="ok", data_mode="synthetic", analysis_mode=analysis_mode,
                  memory_mode=memory_mode, request_id=request.state.request_id)


@router.get("/transactions", response_model=list[Transaction])
def list_transactions(request: Request, limit: int = Query(25, ge=1, le=100)):
    return sorted(request.app.state.transactions, key=lambda t: t.occurred_at, reverse=True)[:limit]


@router.post("/analyses", response_model=Analysis)
async def analyze_transaction(body: AnalyzeRequest, request: Request):
    tx = transaction(request, body.transaction_id)
    prior = prior_confirmation(tx.merchant_category, await remembered(request))
    result = await review(tx, request.app.state.transactions, request.state.request_id, prior,
                          api_key(request), force_live=True)
    record_mode(request, [result])
    return result


@router.get("/alerts", response_model=list[Alert])
async def list_alerts(request: Request):
    return await alerts(request)


@router.get("/privacy/preview/{transaction_id}", response_model=PrivacyPreview)
async def preview(transaction_id: str, request: Request):
    tx = transaction(request, transaction_id)
    prior = prior_confirmation(tx.merchant_category, await remembered(request))
    return privacy_preview(tx, request.app.state.transactions, prior)


@router.post("/alerts/{alert_id}/confirmations", response_model=Confirmation)
async def confirm(alert_id: str, body: ConfirmationRequest, request: Request):
    alert = next((a for a in await alerts(request) if a.alert_id == alert_id), None)
    if alert is None:
        raise HTTPException(404, "not_found")
    state = request.app.state
    owner = state.settings.demo_user_id
    try:
        replay = state.store.replay_confirmation(
            owner, alert_id, body.decision, body.consent_to_memory, request.state.request_id)
    except ConflictingConfirmation:
        raise HTTPException(409, "confirmation_conflict") from None
    if replay is not None:
        return replay
    sentence = memory_sentence(transaction(request, alert.transaction_id), body.decision,
                               body.consent_to_memory, state.settings.allow_memory_write)
    async with vendor_http(request) as http:
        placed = await write_consented_memory(state.store, owner, sentence, api_key(request), http)
        try:
            result = state.store.confirm(
                owner, alert_id, body.decision, body.consent_to_memory, placed.sentence,
                request.state.request_id, memory_id=placed.memory_id, source=placed.source,
                assistant_id=placed.assistant_id, memory_status=placed.status)
        except ConflictingConfirmation:
            if placed.source == "backboard" and placed.memory_id and placed.assistant_id:
                try:
                    await delete_memory(placed.assistant_id, placed.memory_id, api_key(request),
                                        client=http)
                except MemoryCallError:
                    state.memory_outcome = "degraded"
            raise HTTPException(409, "confirmation_conflict") from None
    if placed.outcome:
        state.memory_outcome = placed.outcome
    return result


@router.get("/memories", response_model=list[MemorySummary])
def memories(request: Request):
    return request.app.state.store.list_memories(request.app.state.settings.demo_user_id)


@router.delete("/memories/{memory_id}", status_code=204)
async def delete(memory_id: str, request: Request):
    state = request.app.state
    owner = state.settings.demo_user_id
    try:
        async with vendor_http(request) as http:
            removed = await remove_remote_memory(
                state.store, owner, memory_id, api_key(request), http)
    except KeyError:
        raise HTTPException(404, "not_found") from None
    except MemoryCallError:
        state.memory_outcome = "degraded"
        raise HTTPException(502, "memory_delete_failed") from None
    if not state.store.delete_memory(owner, memory_id):
        raise HTTPException(404, "not_found")
    if removed == "deleted":
        state.memory_outcome = "backboard-live"
    return Response(status_code=204)
