"""Consented memory placement with a durable, non-retrying remote-write intent."""
from dataclasses import dataclass
import sqlite3

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


async def ensure_assistant(store, owner, api_key, client=None):
    existing = store.assistant_id(owner)
    if existing:
        return existing
    created = await create_assistant(api_key, client=client)
    return store.save_assistant(owner, created)


async def complete_list(assistant_id, api_key, client):
    page = await list_memories(assistant_id, api_key, client=client)
    if page.total_count != len(page.memories) or len({item.id for item in page.memories}) != len(page.memories):
        raise MemoryCallError("incomplete_read")
    return page.memories


async def reconcile_job(store, owner, job, api_key, client):
    if job["state"] == "confirmed":
        return job["remote_id"]
    if job["state"] != "pending":
        raise MemoryCallError("uncertain_write")
    rows = await complete_list(job["assistant_id"], api_key, client)
    matches = [row for row in rows if row.id not in job["before_ids"] and row.content == job["sentence"]]
    if len(matches) != 1:
        raise MemoryCallError("uncertain_write")
    try:
        store.update_memory_job(owner, job["alert_id"], "confirmed", matches[0].id)
    except sqlite3.IntegrityError:
        raise MemoryCallError("uncertain_write") from None
    return matches[0].id


async def write_consented_memory(store: Store, owner, sentence, api_key, client=None, *, alert_id):
    if not sentence:
        return MemoryWrite(sentence=None)
    if not approved_memory(sentence):
        return MemoryWrite(sentence=None, status="failed", outcome="degraded")
    if not api_key.strip():
        return MemoryWrite(sentence=sentence, status="written")
    try:
        job = store.memory_job(owner, alert_id=alert_id)
        if job is None:
            assistant_id = await ensure_assistant(store, owner, api_key, client)
            store.prepare_memory_job(owner, alert_id, assistant_id, sentence)
            before = await complete_list(assistant_id, api_key, client)
            if not store.record_memory_baseline(owner, alert_id, [row.id for row in before]):
                return MemoryWrite(None, status="skipped")
            job = store.memory_job(owner, alert_id=alert_id)
            try:
                record = await add_memory(assistant_id, sentence, api_key, client=client)
                if record.content and record.content != sentence:
                    raise MemoryCallError("invalid_response")
                if not store.update_memory_job(owner, alert_id, "confirmed", record.id):
                    return MemoryWrite(None, status="skipped")
                return MemoryWrite(sentence, record.id, "backboard", "written", assistant_id, "backboard-live")
            except MemoryCallError as exc:
                if str(exc) == "rejected":
                    store.update_memory_job(owner, alert_id, "failed")
                    return MemoryWrite(sentence, job["local_id"], status="failed", outcome="degraded")
        remote_id = await reconcile_job(store, owner, job, api_key, client)
        return MemoryWrite(sentence, remote_id, "backboard", "written", job["assistant_id"], "backboard-live")
    except (MemoryCallError, sqlite3.Error, ValueError):
        job = store.memory_job(owner, alert_id=alert_id)
        if job:
            if job["state"] == "deleted":
                return MemoryWrite(None, status="skipped")
            if job["state"] == "preparing":
                store.update_memory_job(owner, alert_id, "failed")
                return MemoryWrite(sentence, job["local_id"], status="failed", outcome="degraded")
            return MemoryWrite(sentence, job["local_id"], status="pending",
                               assistant_id=job["assistant_id"], outcome="degraded")
        return MemoryWrite(sentence, status="failed", outcome="degraded")


async def consented_summaries(store, owner, api_key, client=None):
    # Management reads use the normal database deadline; optional analysis context stays short.
    local = [summary for summary in store.consented_memory_summaries(owner, timeout=5)
             if approved_memory(summary)]
    if not api_key.strip():
        return local, None
    assistant_id = store.assistant_id(owner)
    if not assistant_id:
        return local, None
    try:
        await complete_list(assistant_id, api_key, client)
    except MemoryCallError:
        return local, "degraded"
    # Only locally indexed consented facts may affect analysis, never orphan vendor rows.
    return local, "backboard-live"


async def remove_remote_memory(store, owner, memory_id, api_key, client=None):
    row = store.memory_row(owner, memory_id)
    if row is None:
        raise KeyError(memory_id)
    job = store.memory_job(owner, memory_id=memory_id)
    if job:
        if job["state"] == "preparing":
            store.update_memory_job(owner, job["alert_id"], "deleted")
            return "already_absent"
        if job["state"] in {"deleted", "failed"}:
            return "already_absent"
        remote_id = await reconcile_job(store, owner, job, api_key, client)
        removed = await delete_memory(job["assistant_id"], remote_id, api_key, client=client)
        store.update_memory_job(owner, job["alert_id"], "deleted", remote_id)
        return removed
    if row["source"] != "backboard":
        return "local"
    assistant_id = row["assistant_id"] or store.assistant_id(owner)
    if not assistant_id or not api_key.strip():
        raise MemoryCallError("missing_key")
    return await delete_memory(assistant_id, memory_id, api_key, client=client)
