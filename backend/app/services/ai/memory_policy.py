from app.schemas.transaction import Transaction
from app.services.ai.privacy import CATEGORIES


def memory_sentence(tx: Transaction, decision: str, consent: bool, enabled: bool) -> str | None:
    if decision != "normal" or not consent or not enabled:
        return None
    category = tx.merchant_category if tx.merchant_category in CATEGORIES else "other"
    return f"The demo user explicitly confirmed a {category} alert as normal. Recheck future evidence."
