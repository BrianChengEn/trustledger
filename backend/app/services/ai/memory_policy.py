from typing import Literal

from app.schemas.transaction import Transaction
from app.services.ai.privacy import CATEGORIES

_PREFIX = "The demo user explicitly confirmed a "
_MARK = " alert as normal."
_TAIL = f"{_MARK} Recheck future evidence."


def memory_sentence(tx: Transaction, decision: str, consent: bool, enabled: bool) -> str | None:
    if decision != "normal" or not consent or not enabled:
        return None
    category = tx.merchant_category if tx.merchant_category in CATEGORIES else "other"
    return f"{_PREFIX}{category}{_TAIL}"


def approved_memory(summary: str) -> bool:
    """True only for the exact consented category sentence. Nothing else may be stored."""
    if not summary.startswith(_PREFIX) or not summary.endswith(_TAIL):
        return False
    category = summary[len(_PREFIX):-len(_TAIL)]
    return category in CATEGORIES


def category_of(summary: str) -> str | None:
    """Return the category embedded in an approved sentence, or None."""
    if not approved_memory(summary):
        return None
    return summary[len(_PREFIX):-len(_TAIL)]


def prior_confirmation(category: str, summaries: list[str]) -> Literal["normal", "review", "unknown"]:
    """Map a consented category sentence to a safe label. Review and opt-out write nothing."""
    label = category if category in CATEGORIES else "other"
    for summary in summaries:
        if not summary.startswith(_PREFIX) or _MARK not in summary:
            continue
        found = summary[len(_PREFIX):].split(_MARK, 1)[0]
        if found == label:
            return "normal"
    return "unknown"
