from typing import Annotated

from fastapi import Depends, Request

from app.core.analysis import AnalysisService
from app.core.jev import BackboardJevProvider
from app.core.memory import PriorConfirmations
from app.core.fraud import FraudProvider, select_fraud_provider
from app.services.ai.gemini_explanation import ExplanationCache, GeminiExplanationService
from app.core.transactions import (
    ProviderUnavailable, SQLiteTransactionProvider, TransactionProvider,
    TransactionService, UserContext,
)


def get_transaction_provider(request: Request) -> TransactionProvider:
    """Override this dependency to inject a canonical mock/Data-owned provider."""
    state = request.app.state
    if state.settings.transaction_provider != "synthetic":
        raise ProviderUnavailable()
    return SQLiteTransactionProvider(state.store, state.settings.demo_user_id)


def get_transaction_service(
    request: Request,
    provider: Annotated[TransactionProvider, Depends(get_transaction_provider)],
) -> TransactionService:
    return TransactionService(provider, UserContext(request.app.state.settings.demo_user_id))


Transactions = Annotated[TransactionService, Depends(get_transaction_service)]


def get_fraud_provider(request: Request) -> FraudProvider | None:
    """A key alone never activates inference. Construction never calls the vendor."""
    settings = request.app.state.settings
    if settings.fraud_provider == "backboard-jev":
        return BackboardJevProvider(settings.backboard_api_key)
    return select_fraud_provider(settings.fraud_provider)


def get_prior_confirmations(request: Request) -> PriorConfirmations:
    state = request.app.state
    return PriorConfirmations(lambda: state.store.consented_memory_summaries(state.settings.demo_user_id))


def get_analysis_service(
    transactions: Transactions,
    provider: Annotated[FraudProvider | None, Depends(get_fraud_provider)],
    memory: Annotated[PriorConfirmations, Depends(get_prior_confirmations)],
) -> AnalysisService:
    return AnalysisService(transactions, provider, memory)


Analyses = Annotated[AnalysisService, Depends(get_analysis_service)]


def get_explanation_service(request: Request) -> GeminiExplanationService:
    """Constructs a caller only when a server-side key is configured. Never calls Gemini here."""
    settings = request.app.state.settings
    key = settings.gemini_api_key.get_secret_value().strip()
    cache = getattr(request.app.state, "explanation_cache", None) or ExplanationCache()
    transport = getattr(request.app.state, "explanation_transport", None)
    if key and transport is None:
        try:
            from app.services.ai.gemini_client import GoogleGenAITransport
            transport = GoogleGenAITransport(key, settings.gemini_model, settings.gemini_timeout_ms)
        except ImportError:
            transport = None
    return GeminiExplanationService(
        transport if key else None, configured=bool(key), model=settings.gemini_model, cache=cache)


Explanations = Annotated[GeminiExplanationService, Depends(get_explanation_service)]
