"""Request-scoped F3/F4 orchestration; no persistence or vendor transport."""
from app.core.fraud import FraudProvider, evaluate_fraud
from app.core.transactions import TransactionService
from app.schemas.api import Alert, Analysis
from app.services.ai.privacy import safe_payload
from app.services.ai.rules import analyze


class AnalysisService:
    def __init__(self, transactions: TransactionService, provider: FraudProvider | None = None):
        self.transactions = transactions
        self.provider = provider

    def analyze(self, transaction_id: str, request_id: str) -> Analysis:
        # Use F3's per-request history and list/get consistency checks. All selection
        # remains scoped to its server-created user context and active provider.
        history = self.transactions.history()
        transaction = self.transactions.get_transaction(transaction_id)
        baseline = analyze(transaction, history, request_id)
        features = safe_payload(transaction, history)
        # F4 validates the eight safe features and assessment. It retains the rules
        # result on success and failure; no score/precedence mapping is introduced.
        return evaluate_fraud(baseline, features, self.provider).analysis

    def alerts(self, request_id: str) -> list[Alert]:
        """Rules-derived alerts; GET and confirmation must not trigger provider calls.

        A POST analysis's degraded mode describes that provider attempt only. These
        alerts truthfully remain rules-only; no cross-request result cache is used.
        """
        history = self.transactions.history()
        result = []
        for transaction in sorted(history, key=lambda row: row.id):
            analysis = analyze(transaction, history, request_id)
            if analysis.alert_type != "none":
                result.append(Alert(**analysis.model_dump(), alert_id="alert_" + transaction.id))
        return result
