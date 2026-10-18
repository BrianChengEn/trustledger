from typing import Literal
from pydantic import AwareDatetime
from app.schemas.api import MemorySummary, StrictModel

Failure = Literal['missing_key', 'missing_assistant', 'provider_error',
                  'content_mismatch', 'storage_unavailable', 'verification_limit',
                  'reference_unavailable', 'deletion_not_completed']


class RelevantMemory(MemorySummary):
    verification: Literal['remote_verified', 'local_only', 'unverified']


class RelevantMemories(StrictModel):
    memories: list[RelevantMemory]
    retrieval_mode: Literal['remote_verified', 'local_fallback', 'unavailable']
    checked_at: AwareDatetime | None = None
    failure: Failure | None = None


class DeletionVerification(StrictModel):
    memory_id: str
    status: Literal['absent', 'present', 'unverified']
    checked_at: AwareDatetime | None = None
    failure: Failure | None = None
