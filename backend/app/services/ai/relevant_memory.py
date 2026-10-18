"""Separate read-only context. Never modifies analysis, local indexes or consent."""
import asyncio
from time import monotonic
from datetime import datetime, timezone
import sqlite3
from app.schemas.relevant_memory import RelevantMemories, RelevantMemory, DeletionVerification
from app.services.ai.backboard_client import MemoryCallError, memory_presence
from app.services.ai.memory_policy import approved_memory, prior_confirmation
from app.services.ai.privacy import CATEGORIES

MAX_CHECKS = 20
VERIFICATION_SECONDS = 5.0


def now():
    return datetime.now(timezone.utc)


async def retrieve(store, owner, category, key, client=None):
    try:
        rows = store.relevant_memory_rows(owner)
        assistant = store.assistant_id(owner)
    except sqlite3.Error:
        return RelevantMemories(memories=[], retrieval_mode='unavailable', failure='storage_unavailable')
    category = category if category in CATEGORIES else 'other'
    rows = [r for r in rows if approved_memory(r['summary'])
            and prior_confirmation(category, [r['summary']]) == 'normal']
    result, failure, remote_reads, checks = [], None, 0, 0
    deadline = monotonic() + VERIFICATION_SECONDS
    for row in rows:
        verification = 'local_only'
        if row['source'] == 'backboard':
            verification = 'unverified'
            reason = ('missing_key' if not key.strip() else 'missing_assistant'
                      if not assistant or row['assistant_id'] != assistant else None)
            if reason is None and (checks >= MAX_CHECKS or monotonic() >= deadline):
                reason = 'verification_limit'
            if reason is None:
                checks += 1
                try:
                    remote = await asyncio.wait_for(
                        memory_presence(assistant, row['memory_id'], key, client=client),
                        timeout=max(0.001, deadline - monotonic()))
                    remote_reads += 1
                    if remote is None:
                        continue
                    if remote.content != row['summary'] or not approved_memory(remote.content):
                        failure = 'content_mismatch'
                        continue
                    verification = 'remote_verified'
                except (MemoryCallError, ValueError, TimeoutError):
                    reason = 'provider_error'
            failure = failure or reason
        result.append(RelevantMemory(memory_id=row['memory_id'], summary=row['summary'],
                      created_at=row['created_at'], source=row['source'], verification=verification))
    # Re-read eligibility after network awaits: deleted/revoked references cannot reappear.
    try:
        eligible = {r['memory_id']: r for r in store.relevant_memory_rows(owner)}
        result = [r for r in result if r.memory_id in eligible
                  and eligible[r.memory_id]['summary'] == r.summary]
    except sqlite3.Error:
        return RelevantMemories(memories=[], retrieval_mode='unavailable', failure='storage_unavailable')
    verified = bool(remote_reads) and not failure and all(r.verification == 'remote_verified' for r in result)
    return RelevantMemories(memories=result,
        retrieval_mode=('remote_verified' if verified else 'unavailable' if failure and not result
                        else 'local_fallback'),
        checked_at=now() if verified else None, failure=failure)


async def deletion_status(store, owner, memory_id, key, client=None):
    try:
        row = store.memory_row(owner, memory_id)
        job = store.memory_job(owner, memory_id=memory_id)
        known = bool(row or job or store.has_memory_confirmation(owner, memory_id))
    except sqlite3.Error:
        return DeletionVerification(memory_id=memory_id, status='unverified', failure='storage_unavailable')
    if not known:
        return None
    if row is not None:
        return DeletionVerification(memory_id=memory_id, status='unverified', failure='deletion_not_completed')
    if not job or not job['remote_id']:
        return DeletionVerification(memory_id=memory_id, status='unverified', failure='reference_unavailable')
    if job['state'] != 'deleted':
        return DeletionVerification(memory_id=memory_id, status='unverified', failure='deletion_not_completed')
    if not key.strip():
        return DeletionVerification(memory_id=memory_id, status='unverified', failure='missing_key')
    try:
        remote = await asyncio.wait_for(
            memory_presence(job['assistant_id'], job['remote_id'], key, client=client),
            timeout=VERIFICATION_SECONDS)
    except (MemoryCallError, ValueError, TimeoutError):
        return DeletionVerification(memory_id=memory_id, status='unverified', failure='provider_error')
    return DeletionVerification(memory_id=memory_id, status='absent' if remote is None else 'present',
                                checked_at=now())
