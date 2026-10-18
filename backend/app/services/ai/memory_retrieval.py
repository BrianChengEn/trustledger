"""Relevant consented memory for a later alert. This never approves the new alert."""
from dataclasses import dataclass
from typing import Literal

from app.services.ai.backboard_client import MemoryCallError, search_memories
from app.services.ai.memory_policy import category_of
from app.services.ai.privacy import CATEGORIES

MemoryState = Literal["backboard-live", "local-fallback", "unavailable", "no-relevant-memory"]
Retrieval = Literal["backboard-search", "category-filter"]


@dataclass(frozen=True)
class MemoryMatch:
    status: MemoryState
    retrieval: Retrieval | None = None
    memory_id: str | None = None
    summary: str | None = None
    source: Literal["backboard", "local-fallback"] | None = None


def category_query(category: str) -> str:
    """Privacy-safe search text. Category label only; no merchant, amount, or id."""
    label = category if category in CATEGORIES else "other"
    return f"confirmed a {label} alert as normal"


def _local(matches: list[dict[str, str]]) -> MemoryMatch:
    if not matches:
        return MemoryMatch("no-relevant-memory", "category-filter")
    row = matches[0]
    return MemoryMatch(
        "local-fallback", "category-filter", row["memory_id"], row["summary"], "local-fallback")


async def find_relevant_memory(store, owner: str, category: str, api_key: str, client=None) -> MemoryMatch:
    """Return one consented same-category memory, or a truthful empty/error state.

    Backboard search is semantic. A hit is accepted only when its id and exact
    sentence match this owner's consented row for the alert category. The score
    is ignored. Results are not cached.
    """
    label = category if category in CATEGORIES else "other"
    try:
        rows = store.consented_memory_records(owner)
    except Exception:
        return MemoryMatch("unavailable")
    matches = [row for row in rows if category_of(row["summary"]) == label]
    if not api_key.strip() or not any(row["source"] == "backboard" for row in matches):
        return _local(matches)
    try:
        assistant_id = store.assistant_id(owner)
    except Exception:
        return MemoryMatch("unavailable")
    if not assistant_id:
        return _local(matches)
    try:
        page = await search_memories(
            assistant_id, category_query(label), api_key, limit=5, client=client)
    except MemoryCallError:
        return MemoryMatch("unavailable")
    by_id = {row["memory_id"]: row for row in matches if row["source"] == "backboard"}
    for remote in page.memories:
        row = by_id.get(remote.id)
        if row is None or row["summary"] != remote.content or category_of(remote.content) != label:
            continue
        return MemoryMatch("backboard-live", "backboard-search", row["memory_id"], row["summary"], "backboard")
    # Search ran and did not corroborate the row. Keep the consented local sentence
    # visible, but do not call that a live or semantic match.
    return _local(matches)
