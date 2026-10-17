from app.schemas.api import FieldAction, PrivacyPreview, SafePayload
from app.schemas.transaction import Transaction

# Only controlled labels can enter model-facing features. User/merchant text never passes through.
CATEGORIES = frozenset({
    "dining", "groceries", "streaming", "electronics", "transportation",
    "fitness_subscription", "other",
})


def prior_transactions(tx: Transaction, history: list[Transaction]) -> list[Transaction]:
    return [h for h in history if h.id != tx.id and h.occurred_at <= tx.occurred_at
            and h.account_token == tx.account_token and h.currency == tx.currency
            and h.direction == tx.direction]


def subscription_delta(tx: Transaction, history: list[Transaction]) -> float | None:
    prior = [h for h in prior_transactions(tx, history) if h.is_subscription
             and h.merchant_display == tx.merchant_display and h.amount > 0]
    if not tx.is_subscription or not prior:
        return None
    previous = max(prior, key=lambda h: h.occurred_at)
    return (tx.amount - previous.amount) / previous.amount


def same_charge_count(tx: Transaction, history: list[Transaction]) -> int:
    prior = prior_transactions(tx, history)
    return min(20, 1 + sum(
        h.amount == tx.amount and h.merchant_category == tx.merchant_category
        and 0 <= (tx.occurred_at - h.occurred_at).total_seconds() <= 86400 for h in prior
    ))


def safe_payload(
    tx: Transaction,
    history: list[Transaction],
    prior_user_confirmation: str = "unknown",
) -> SafePayload:
    amount_bucket = next((label for ceiling, label in [
        (10, "0-10"), (25, "10-25"), (50, "25-50"), (100, "50-100"), (250, "100-250")
    ] if tx.amount < ceiling), "250+")
    hour = tx.occurred_at.hour
    day_part = "morning" if 6 <= hour < 12 else "afternoon" if 12 <= hour < 18 else (
        "evening" if 18 <= hour < 24 else "overnight"
    )
    delta = subscription_delta(tx, history)
    delta_bucket = "unknown" if delta is None else (
        "over-20-percent" if delta > .2 else "up-to-20-percent" if delta > 0 else "none"
    )
    return SafePayload(
        merchant_category=tx.merchant_category if tx.merchant_category in CATEGORIES else "other",
        amount_bucket=amount_bucket, currency=tx.currency, local_day_part=day_part,
        same_category_same_amount_24h_count=same_charge_count(tx, history),
        is_subscription=tx.is_subscription, subscription_delta_bucket=delta_bucket,
        prior_user_confirmation=prior_user_confirmation,
    )


def privacy_preview(
    tx: Transaction,
    history: list[Transaction],
    prior_user_confirmation: str = "unknown",
) -> PrivacyPreview:
    payload = safe_payload(tx, history, prior_user_confirmation)
    return PrivacyPreview(transaction_id=tx.id, safe_payload=payload, inspection=[
        FieldAction(field="id / account_token", action="dropped", reason="No identifiers in AI payload."),
        FieldAction(field="merchant_display", action="dropped", reason="Raw merchant text is not sent."),
        FieldAction(field="merchant_category", action="generalized", output=payload.merchant_category,
                    reason="Controlled category vocabulary only."),
        FieldAction(field="amount", action="bucketed", output=payload.amount_bucket,
                    reason="Exact money value removed."),
        FieldAction(field="occurred_at", action="bucketed", output=payload.local_day_part,
                    reason="Exact date and time removed."),
        FieldAction(field="prior_user_confirmation", action="allowed",
                    output=payload.prior_user_confirmation,
                    reason="Consented category label only. No merchant, amount, or id."),
        FieldAction(field="unknown fields / PII / API keys", action="dropped",
                    reason="Eight approved features only. A live call sends them as Backboard state."),
    ])
