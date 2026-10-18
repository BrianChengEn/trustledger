from app.schemas.relevant_memory import RelevantMemories, DeletionVerification
from app.services.ai.relevant_memory import retrieve, deletion_status
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response

from contextlib import asynccontextmanager
import httpx

from app.api.dependencies import Analyses, Explanations, Transactions
from app.core.auth import require_admin_when_enforced, require_session
from app.core.store import ConflictingConfirmation
from app.schemas.api import (
    Alert, Analysis, AnalyzeRequest, Confirmation, ConfirmationRequest, Explanation, Health,
    MemorySummary, PrivacyPreview,
)
from app.schemas.transaction import Transaction
from app.services.ai.memory_policy import memory_sentence
from app.services.ai.backboard_client import MemoryCallError
from app.services.ai.memory_sync import consented_summaries, remove_remote_memory, write_consented_memory
from app.services.workspace import owner as workspace_owner, require_nessie, select_customer

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_session), Depends(require_nessie)])
customer_router = APIRouter(prefix='/api/v1/admin/nessie/customers/{customer_code}',
                            dependencies=[Depends(require_admin_when_enforced), Depends(select_customer), Depends(require_nessie)])


def private_markers(tx: Transaction) -> tuple[str, ...]:
    """Local denylist for model output. These values are not placed in the Gemini document."""
    amount = tx.amount
    markers = [
        tx.id, tx.account_token, tx.merchant_display, tx.occurred_at.isoformat(),
        str(amount), f"{amount:.2f}", f"{amount:.1f}", f"{amount:g}",
    ]
    unique: list[str] = []
    for marker in markers:
        if len(marker) >= 3 and marker not in unique:
            unique.append(marker)
    return tuple(unique)


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
            state.store, workspace_owner(request), api_key(request), http)
    if outcome and (outcome == "degraded" or getattr(state, "memory_outcome", None) != "degraded"):
        state.memory_outcome = outcome
    return summaries


def alerts(request: Request, analyses: Analyses) -> list[Alert]:
    state = request.app.state
    # GET and confirmation never invoke a fraud provider.
    result = analyses.alerts(request.state.request_id)
    for alert in result:
        alert.status = state.store.status(workspace_owner(request), alert.alert_id)
    return result


@router.get("/health", response_model=Health)
@customer_router.get('/health', response_model=Health)
def health(request: Request, transactions: Transactions):
    # Report current data readiness, not a previous request's cached AI outcome.
    # Public analysis remains rules-authoritative; failures are request-specific.
    provider_health = transactions.health()
    memory_mode = (getattr(request.app.state, "memory_outcome", None) or "local-fallback"
                   if request.app.state.settings.allow_memory_write else "off")
    status = "degraded" if memory_mode == "degraded" else provider_health.status
    return Health(status=status, data_mode=provider_health.data_mode, analysis_mode="rules-only",
                  memory_mode=memory_mode,
                  request_id=request.state.request_id)


@router.get("/transactions", response_model=list[Transaction])
@customer_router.get('/transactions', response_model=list[Transaction])
def list_transactions(transactions: Transactions, limit: int = Query(25, ge=1, le=100)):
    return transactions.list_transactions(limit)


@router.post("/analyses", response_model=Analysis)
@customer_router.post('/analyses', response_model=Analysis)
def analyze_transaction(body: AnalyzeRequest, request: Request, analyses: Analyses):
    return analyses.analyze(body.transaction_id, request.state.request_id)


@router.get("/alerts", response_model=list[Alert])
@customer_router.get('/alerts', response_model=list[Alert])
def list_alerts(request: Request, analyses: Analyses):
    return alerts(request, analyses)


@router.get("/privacy/preview/{transaction_id}", response_model=PrivacyPreview)
@customer_router.get('/privacy/preview/{transaction_id}', response_model=PrivacyPreview)
def preview(transaction_id: Annotated[str, Path(min_length=1, max_length=80)],
            analyses: Analyses):
    return analyses.preview(transaction_id)


@router.post("/transactions/{transaction_id}/explanation", response_model=Explanation)
@customer_router.post('/transactions/{transaction_id}/explanation', response_model=Explanation)
def explain_transaction(transaction_id: Annotated[str, Path(min_length=1, max_length=80)],
                        request: Request, analyses: Analyses, explanations: Explanations):
    """User-triggered explanation. Rules stay authoritative; Gemini is not called by analysis."""
    analysis, features = analyses.rules_view(transaction_id, request.state.request_id)
    before = analysis.model_dump_json()
    transaction = analyses.transactions.get_transaction(transaction_id)
    result = explanations.explain(analysis, features, private_markers(transaction))
    if analysis.model_dump_json() != before:
        raise HTTPException(500, "internal_error")
    return result


@router.post("/alerts/{alert_id}/confirmations", response_model=Confirmation)
@customer_router.post('/alerts/{alert_id}/confirmations', response_model=Confirmation)
async def confirm(alert_id: Annotated[str, Path(min_length=1, max_length=80)],
                  body: ConfirmationRequest, request: Request, transactions: Transactions, analyses: Analyses):
    state = request.app.state
    owner = workspace_owner(request)
    try:
        replay = state.store.replay_confirmation(
            owner, alert_id, body.decision, body.consent_to_memory, request.state.request_id)
        if replay is not None:
            return replay
        alert = next((a for a in alerts(request, analyses) if a.alert_id == alert_id), None)
        if alert is None:
            raise HTTPException(404, "not_found")
        sentence = memory_sentence(transactions.get_transaction(alert.transaction_id), body.decision,
                                   body.consent_to_memory, state.settings.allow_memory_write)
        result, claimed = state.store.claim_confirmation(
            owner, alert_id, body.decision, body.consent_to_memory, bool(sentence), request.state.request_id)
    except ConflictingConfirmation:
        raise HTTPException(409, "confirmation_conflict") from None
    if not claimed or not sentence:
        return result
    if not api_key(request).strip():
        return state.store.complete_local_memory(owner, sentence, result)
    try:
        async with vendor_http(request) as http:
            placed = await write_consented_memory(state.store, owner, sentence, api_key(request), http,
                                                 alert_id=alert_id)
        result = state.store.finish_memory(
            owner, result, placed.sentence, memory_id=placed.memory_id, source=placed.source,
            assistant_id=placed.assistant_id, memory_status=placed.status)
    except Exception:
        # The confirmation already committed. An interrupted optional operation may
        # have reached the vendor; retain its durable state without retrying.
        state.memory_outcome = "degraded"
        try:
            return state.store.replay_confirmation(
                owner, alert_id, body.decision, body.consent_to_memory, request.state.request_id)
        except Exception:
            return result
    if placed.outcome:
        state.memory_outcome = "degraded" if result.memory_status == "pending" else placed.outcome
    return result


@router.get("/memories", response_model=list[MemorySummary])
@customer_router.get('/memories', response_model=list[MemorySummary])
async def memories(request: Request):
    await remembered(request)
    return request.app.state.store.list_memories(workspace_owner(request))


@router.delete("/memories/{memory_id}", status_code=204)
@customer_router.delete('/memories/{memory_id}', status_code=204)
async def delete(memory_id: Annotated[str, Path(min_length=1, max_length=100)], request: Request):
    state = request.app.state
    owner = workspace_owner(request)
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


@router.get('/transactions/{transaction_id}/relevant-memories', response_model=RelevantMemories)
@customer_router.get('/transactions/{transaction_id}/relevant-memories', response_model=RelevantMemories)
async def relevant_memories(transaction_id: Annotated[str, Path(min_length=1, max_length=80)],
                            request: Request, transactions: Transactions):
    tx = transactions.get_transaction(transaction_id)
    async with vendor_http(request) as http:
        return await retrieve(request.app.state.store, workspace_owner(request),
                              tx.merchant_category, api_key(request), http)


@router.get('/memories/{memory_id}/deletion-verification', response_model=DeletionVerification)
@customer_router.get('/memories/{memory_id}/deletion-verification', response_model=DeletionVerification)
async def verify_deletion(memory_id: Annotated[str, Path(min_length=1, max_length=100)], request: Request):
    async with vendor_http(request) as http:
        result = await deletion_status(request.app.state.store, workspace_owner(request),
                                       memory_id, api_key(request), http)
    if result is None:
        raise HTTPException(404, 'not_found')
    return result
