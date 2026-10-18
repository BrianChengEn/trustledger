"""Manual Backboard memory CRUD. Jev inference does not turn memory on."""

import re
from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict

from app.services.ai.memory_policy import approved_memory

API_ROOT = "https://app.backboard.io/api"
ASSISTANT_NAME = "TrustLedger preference memory"
ASSISTANT_PROMPT = (
    "Store only an explicit category confirmation. "
    "Do not keep names, account numbers, merchants, or transactions."
)
_MEMORY_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class MemoryCallError(Exception):
    """Safe failure. The message is a code, never a response body or credential."""


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    content: str
    score: float | None = None
    created_at: str | None = None


class MemoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memories: list[MemoryRecord]
    total_count: int


def _assistant_id(value: object) -> str:
    if not isinstance(value, str):
        raise MemoryCallError("invalid_response")
    try:
        return str(UUID(value))
    except ValueError:
        raise MemoryCallError("invalid_response") from None


def _memory_id(value: object) -> str:
    if not isinstance(value, str) or _MEMORY_ID.fullmatch(value) is None:
        raise MemoryCallError("invalid_response")
    return value


def _text(value: object, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise MemoryCallError("invalid_response")
    return value


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MemoryCallError("invalid_response")
    return float(value)


def _count(value: object, *, required: bool) -> int:
    if value is None and not required:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise MemoryCallError("invalid_response")
    return value


def _record(item: object, *, search: bool) -> MemoryRecord:
    if not isinstance(item, dict):
        raise MemoryCallError("invalid_response")
    created = item.get("created_at")
    if created is not None and not isinstance(created, str):
        raise MemoryCallError("invalid_response")
    updated = item.get("updated_at")
    if updated is not None and not isinstance(updated, str):
        raise MemoryCallError("invalid_response")
    metadata = item.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise MemoryCallError("invalid_response")
    content = _text(item.get("content"), required=True)
    return MemoryRecord(
        id=_memory_id(item.get("id")),
        content=content or "",
        score=_number(item.get("score")) if search or "score" in item else None,
        created_at=created,
    )


def parse_created(data: object) -> MemoryRecord:
    """Add Memory returns 201 with an open object. The docs read memory_id; GET uses id."""
    if not isinstance(data, dict):
        raise MemoryCallError("invalid_response")
    if "memory_id" in data and "id" in data and data["memory_id"] != data["id"]:
        raise MemoryCallError("invalid_response")
    raw_id = data["memory_id"] if "memory_id" in data else data.get("id")
    content = data.get("content")
    if content is not None and not isinstance(content, str):
        raise MemoryCallError("invalid_response")
    return MemoryRecord(id=_memory_id(raw_id), content=content or "")


def parse_memory(data: object) -> MemoryRecord:
    return _record(data, search=False)


def parse_list(data: object) -> MemoryPage:
    if not isinstance(data, dict):
        raise MemoryCallError("invalid_response")
    rows = data.get("memories", [])
    if not isinstance(rows, list):
        raise MemoryCallError("invalid_response")
    for field in ("page", "page_size", "total_pages"):
        value = data.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise MemoryCallError("invalid_response")
    return MemoryPage(
        memories=[_record(item, search=False) for item in rows],
        total_count=_count(data.get("total_count", 0), required=False),
    )


def parse_search(data: object) -> MemoryPage:
    if not isinstance(data, dict) or "memories" not in data or "total_count" not in data:
        raise MemoryCallError("invalid_response")
    rows = data["memories"]
    if not isinstance(rows, list):
        raise MemoryCallError("invalid_response")
    return MemoryPage(
        memories=[_record(item, search=True) for item in rows],
        total_count=_count(data["total_count"], required=True),
    )


def parse_delete(data: object) -> Literal["deleted"]:
    if not isinstance(data, dict):
        raise MemoryCallError("invalid_response")
    success = data.get("success")
    message = data.get("message")
    if not isinstance(success, bool) or not isinstance(message, str):
        raise MemoryCallError("invalid_response")
    if not success:
        raise MemoryCallError("not_deleted")
    return "deleted"


def parse_assistant(data: object) -> str:
    if not isinstance(data, dict):
        raise MemoryCallError("invalid_response")
    name = data.get("name")
    created = data.get("created_at")
    if not isinstance(name, str) or not name.strip() or not isinstance(created, str) or not created.strip():
        raise MemoryCallError("invalid_response")
    return _assistant_id(data.get("assistant_id"))


async def _send(
    method: str,
    url: str,
    api_key: str,
    client: httpx.AsyncClient | None,
    *,
    json: dict | None = None,
    ok: set[int],
) -> object:
    key = api_key.strip()
    if not key:
        raise MemoryCallError("missing_key")
    headers = {"X-API-Key": key, "Content-Type": "application/json"}

    async def once(http: httpx.AsyncClient) -> object:
        try:
            response = await http.request(method, url, headers=headers, json=json)
        except httpx.HTTPError:
            raise MemoryCallError("request_failed") from None
        if response.status_code == 404 and method == "DELETE":
            raise MemoryCallError("already_absent")
        if response.status_code not in ok:
            raise MemoryCallError("request_failed")
        try:
            return response.json()
        except ValueError:
            raise MemoryCallError("invalid_response") from None

    if client is not None:
        return await once(client)
    async with httpx.AsyncClient(timeout=8.0) as http:
        return await once(http)


async def create_assistant(api_key: str, *, client: httpx.AsyncClient | None = None) -> str:
    """POST /assistants. The body is a fixed label, never a demo user or transaction."""
    data = await _send(
        "POST", f"{API_ROOT}/assistants", api_key, client,
        json={"name": ASSISTANT_NAME, "system_prompt": ASSISTANT_PROMPT}, ok={200},
    )
    return parse_assistant(data)


async def add_memory(
    assistant_id: str,
    content: str,
    api_key: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> MemoryRecord:
    if not approved_memory(content):
        raise MemoryCallError("unsafe_content")
    assistant = _assistant_id(assistant_id)
    data = await _send(
        "POST", f"{API_ROOT}/assistants/{assistant}/memories", api_key, client,
        json={"content": content}, ok={201},
    )
    try:
        return parse_created(data)
    except MemoryCallError:
        await _drop_unparsed(assistant, data, api_key, client)
        raise


async def _drop_unparsed(
    assistant_id: str,
    data: object,
    api_key: str,
    client: httpx.AsyncClient | None,
) -> None:
    """Remove a created memory we cannot index, so a local row is not a second copy."""
    if not isinstance(data, dict):
        return
    raw = data["memory_id"] if "memory_id" in data else data.get("id")
    if not isinstance(raw, str) or _MEMORY_ID.fullmatch(raw) is None:
        return
    try:
        await delete_memory(assistant_id, raw, api_key, client=client)
    except MemoryCallError:
        return


async def list_memories(
    assistant_id: str,
    api_key: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> MemoryPage:
    assistant = _assistant_id(assistant_id)
    data = await _send(
        "GET", f"{API_ROOT}/assistants/{assistant}/memories", api_key, client, ok={200},
    )
    return parse_list(data)


async def get_memory(
    assistant_id: str,
    memory_id: str,
    api_key: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> MemoryRecord:
    assistant = _assistant_id(assistant_id)
    data = await _send(
        "GET", f"{API_ROOT}/assistants/{assistant}/memories/{_memory_id(memory_id)}",
        api_key, client, ok={200},
    )
    return parse_memory(data)


async def search_memories(
    assistant_id: str,
    query: str,
    api_key: str,
    *,
    limit: int = 5,
    client: httpx.AsyncClient | None = None,
) -> MemoryPage:
    if not isinstance(query, str) or not query.strip():
        raise MemoryCallError("invalid_response")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise MemoryCallError("invalid_response")
    assistant = _assistant_id(assistant_id)
    data = await _send(
        "POST", f"{API_ROOT}/assistants/{assistant}/memories/search", api_key, client,
        json={"query": query, "limit": limit}, ok={200},
    )
    return parse_search(data)


async def delete_memory(
    assistant_id: str,
    memory_id: str,
    api_key: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> Literal["deleted", "already_absent"]:
    assistant = _assistant_id(assistant_id)
    url = f"{API_ROOT}/assistants/{assistant}/memories/{_memory_id(memory_id)}"
    try:
        data = await _send("DELETE", url, api_key, client, ok={200})
    except MemoryCallError as exc:
        if str(exc) == "already_absent":
            return "already_absent"
        raise
    return parse_delete(data)
