"""Request-local, consent-proven local memory context; never a risk decision."""
import re
from collections.abc import Callable

from app.services.ai.memory_policy import prior_confirmation
from app.services.ai.privacy import CATEGORIES

_SENTENCE = re.compile(
    r"The demo user explicitly confirmed a ([a-z_]+) alert as normal\. Recheck future evidence\."
)


class PriorConfirmations:
    def __init__(self, load: Callable[[], list[str]] = lambda: []):
        self._load = load
        self._summaries: list[str] | None = None

    def for_category(self, category: str) -> str:
        if self._summaries is None:
            self._summaries = []
            try:
                for sentence in self._load():
                    match = _SENTENCE.fullmatch(sentence)
                    if match and match[1] in CATEGORIES:
                        self._summaries.append(sentence)
            except Exception:
                # Failed/malformed memory is unavailable context, not evidence of safety.
                self._summaries = []
        try:
            return prior_confirmation(category, self._summaries)
        except Exception:
            return "unknown"
