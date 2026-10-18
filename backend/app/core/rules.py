"""Approved backend semantics; Main direct decision policy remains separate."""
from app.schemas.api import Analysis
from app.schemas.transaction import Transaction
from app.core.features import prior_transactions, subscription_delta


def analyze(
    tx: Transaction,
    history: list[Transaction],
    request_id: str,
    prior_user_confirmation: str = "unknown",
) -> Analysis:
    """Deterministic demo heuristics, not a fraud probability or financial decision."""
    prior = prior_transactions(tx, history)
    # shortcut: Nessie has no validated merchant grouping; enable duplicate checks after adding one.
    duplicate = tx.source != 'nessie' and not tx._date_only and any(not h._date_only and h.merchant_display == tx.merchant_display and h.amount == tx.amount
                    and 0 <= (tx.occurred_at - h.occurred_at).total_seconds() <= 86400
                    for h in prior)
    delta = subscription_delta(tx, history)
    kind, severity, evidence = "none", "low", ["No demo rule requires attention."]
    if duplicate and tx.direction == "debit":
        kind, severity = "duplicate", "medium"
        evidence = ["Another charge to the same merchant for the same amount occurred within 24 hours."]
    elif tx.amount >= 250 and tx.direction == "debit":
        kind, severity = "amount_anomaly", "high"
        evidence = ["Amount exceeds the demo high-amount threshold; please check the purchase."]
    elif delta is not None and delta > .2 and tx.direction == "debit":
        kind, severity = "subscription_change", "medium"
        evidence = ["This recurring charge increased by more than 20 percent versus the previous charge."]
    if tx._settlement_status != 'completed':
        kind, severity, evidence = 'none', 'low', ['This record is not completed; completed-charge rules do not apply.']
    if kind == 'none' and tx._settlement_status == 'completed' and tx.direction == 'unknown':
        evidence = ['Insufficient evidence: transaction direction is unknown; debit rules cannot be evaluated. This is not a safe verdict.']
    if prior_user_confirmation == "normal" and kind != "none":
        evidence = [*evidence, "A prior consented confirmation marked this category as normal. "
                    "This match still needs a person."]
    return Analysis(transaction_id=tx.id, alert_type=kind, severity=severity,
                    needs_human=kind != "none", confidence=1.0,
                    evidence=evidence, request_id=request_id)


def evaluation_outcome(tx: Transaction, analysis: Analysis | None = None) -> str:
    """Interpret rule coverage without changing approved thresholds or the public DTO.

    Provider/HTTP exceptions remain ANALYSIS_FAILED at the existing typed error boundary.
    """
    if analysis is not None and analysis.alert_type != 'none':
        return 'ALERT_GENERATED'
    if tx._settlement_status != 'completed':
        return 'RULE_NOT_APPLICABLE'
    if tx.direction == 'unknown':
        return 'INSUFFICIENT_EVIDENCE'
    if tx.direction != 'debit':
        return 'RULE_NOT_APPLICABLE'
    return 'EVALUATED_NO_ALERT'
