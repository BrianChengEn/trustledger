"""Consented memory placement. SQLite remains the record the API returns."""

from dataclasses import dataclass

import httpx

from app.core.store import Store
from app.services.ai.backboard_client import (
    MemoryCallError, add_memory, create_assistant, delete_memory, list_memories,
)
from app.services.ai.memory_policy import approved_memory


@dataclass(frozen=True)
class MemoryWrite:
    sentence: str | None
    memory_id: str | None = None
    source: str = "local-fallback"
    status: str | None = None
    assistant_id: str | None = None
    outcome: str | None = None


async def ensure_assistant(
    store: Store,
    owner: str,
    api_key: str,
    client: httpx.AsyncClient | None = None,
) -> str:
    existing = store.assistant_id(owner)
    if existing:
        return existing
    created = await create_assistant(api_key, client=client)
    return store.save_assistant(owner, created)


async def write_consented_memory(
    store: Store,
    owner: str,
    sentence: str | None,
    api_key: str,
    client: httpx.AsyncClient | None = None,
) -> MemoryWrite:
    """One local row. Remote success is the only path labeled backboard."""
    if not sentence:
        return MemoryWrite(sentence=None)
    if not approved_memory(sentence):
        return MemoryWrite(sentence=None, status="failed", outcome="degraded")
    if not api_key.strip():
        return MemoryWrite(sentence=sentence, status="written")
    try:
        assistant_id = await ensure_assistant(store, owner, api_key, client)
        record = await add_memory(assistant_id, sentence, api_key, client=client)
    except MemoryCallError:
        return MemoryWrite(sentence=sentence, status="failed", outcome="degraded")
    return MemoryWrite(
        sentence=sentence, memory_id=record.id, source="backboard", status="written",
        assistant_id=assistant_id, outcome="backboard-live",
    )


async def consented_summaries(
    store: Store,
    owner: str,
    api_key: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[str], str | None]:
    """Local sentences, plus this owner's remote sentences when a list call succeeds."""
    local = [item.summary for item in store.list_memories(owner)]
    if not api_key.strip():
        return local, None
    assistant_id = store.assistant_id(owner)
    if not assistant_id:
        return local, None
    try:
        page = await list_memories(assistant_id, api_key, client=client)
    except MemoryCallError:
        return local, "degraded"
    merged = list(local)
    for item in page.memories:
        if approved_memory(item.content) and item.content not in merged:
            merged.append(item.content)
    return merged, "backboard-live"


async def remove_remote_memory(
    store: Store,
    owner: str,
    memory_id: str,
    api_key: str,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Return local, deleted, or already_absent. Raise when the remote row must stay."""
    row = store.memory_row(owner, memory_id)
    if row is None:
        raise KeyError(memory_id)
    if row["source"] != "backboard":
        return "local"
    assistant_id = row["assistant_id"] or store.assistant_id(owner)
    if not assistant_id or not api_key.strip():
        raise MemoryCallError("missing_key")
    return await delete_memory(assistant_id, memory_id, api_key, client=client)
