from typing import Annotated

from fastapi import Depends, Request

from app.core.analysis import AnalysisService
from app.core.fraud import FraudProvider, select_fraud_provider
from app.core.transactions import (
    ProviderUnavailable, SyntheticTransactionProvider, TransactionProvider,
    TransactionService, UserContext,
)


def get_transaction_provider(request: Request) -> TransactionProvider:
    """Override this dependency to inject a canonical mock/Data-owned provider."""
    state = request.app.state
    if state.settings.transaction_provider != "synthetic":
        raise ProviderUnavailable()
    return SyntheticTransactionProvider(state.transactions, state.settings.demo_user_id)


def get_transaction_service(
    request: Request,
    provider: Annotated[TransactionProvider, Depends(get_transaction_provider)],
) -> TransactionService:
    return TransactionService(provider, UserContext(request.app.state.settings.demo_user_id))


Transactions = Annotated[TransactionService, Depends(get_transaction_service)]


def get_fraud_provider(request: Request) -> FraudProvider | None:
    """Only local rules/mock modes; override for deterministic provider tests."""
    return select_fraud_provider(request.app.state.settings.fraud_provider)


def get_analysis_service(
    transactions: Transactions,
    provider: Annotated[FraudProvider | None, Depends(get_fraud_provider)],
) -> AnalysisService:
    return AnalysisService(transactions, provider)


Analyses = Annotated[AnalysisService, Depends(get_analysis_service)]
