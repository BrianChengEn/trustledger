from statistics import median

from app.schemas.api import Analysis
from app.schemas.transaction import Transaction
from app.services.ai.privacy import prior_transactions, subscription_delta
from app.services.ai.policy import (
    DAY_SECONDS, HIGH_AMOUNT_MINIMUM, HIGH_AMOUNT_MULTIPLIER, HISTORY_DAYS,
    SPARSE_HISTORY_HIGH_AMOUNT, SUBSCRIPTION_INCREASE,
)


def analyze(
    tx: Transaction,
    history: list[Transaction],
    request_id: str,
    prior_user_confirmation: str = "unknown",
) -> Analysis:
    """Deterministic demo heuristics, not a fraud probability or financial decision."""
    prior = prior_transactions(tx, history)
    duplicate = any(h.merchant_category == tx.merchant_category and h.amount == tx.amount
                    and 0 <= (tx.occurred_at - h.occurred_at).total_seconds() <= DAY_SECONDS
                    for h in prior)
    amounts = [h.amount for h in prior if h.merchant_category == tx.merchant_category
               and 0 <= (tx.occurred_at - h.occurred_at).total_seconds() <= HISTORY_DAYS * DAY_SECONDS]
    high_amount = (tx.amount > max(HIGH_AMOUNT_MINIMUM, HIGH_AMOUNT_MULTIPLIER * median(amounts))
                   if amounts else tx.amount >= SPARSE_HISTORY_HIGH_AMOUNT)
    delta = subscription_delta(tx, history)
    kind, severity, evidence = "none", "low", ["No demo rule requires attention."]
    if duplicate and tx.direction == "debit":
        kind, severity = "duplicate", "medium"
        evidence = ["Another charge in the same category for the same amount occurred within 24 hours."]
    elif high_amount and tx.direction == "debit":
        kind, severity = "amount_anomaly", "high"
        evidence = ["Amount exceeds the demo high-amount threshold; please check the purchase."]
    elif delta is not None and delta > SUBSCRIPTION_INCREASE and tx.direction == "debit":
        kind, severity = "subscription_change", "medium"
        evidence = ["This recurring charge increased by more than 20 percent versus the previous charge."]
    if prior_user_confirmation == "normal" and kind != "none":
        evidence = [*evidence, "A prior consented confirmation marked this category as normal. "
                    "This match still needs a person."]
    return Analysis(transaction_id=tx.id, alert_type=kind, severity=severity,
                    needs_human=kind != "none", confidence=1.0,
                    evidence=evidence, request_id=request_id)
