from typing import Literal

from app.schemas.transaction import Transaction
from app.services.ai.privacy import CATEGORIES

_PREFIX = "The demo user explicitly confirmed a "
_MARK = " alert as normal."


def memory_sentence(tx: Transaction, decision: str, consent: bool, enabled: bool) -> str | None:
    if decision != "normal" or not consent or not enabled:
        return None
    category = tx.merchant_category if tx.merchant_category in CATEGORIES else "other"
    return f"{_PREFIX}{category}{_MARK} Recheck future evidence."


def prior_confirmation(category: str, summaries: list[str]) -> Literal["normal", "review", "unknown"]:
    """Map consented local-fallback sentences to a safe label. Review and opt-out write nothing."""
    label = category if category in CATEGORIES else "other"
    for summary in summaries:
        if not summary.startswith(_PREFIX) or _MARK not in summary:
            continue
        found = summary[len(_PREFIX):].split(_MARK, 1)[0]
        if found == label:
            return "normal"
    return "unknown"
