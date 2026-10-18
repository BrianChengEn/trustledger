import asyncio
import json
import sqlite3

import httpx

from app.adapters.synthetic import load_transactions
from app.core.store import Store
from app.services.ai.backboard_client import (
    ASSISTANT_NAME, MemoryCallError, add_memory, delete_memory, get_memory, list_memories,
    parse_created, parse_search, search_memories,
)
from app.services.ai.memory_policy import approved_memory, memory_sentence
from app.services.ai.memory_sync import consented_summaries, write_consented_memory as write_placed_memory

async def write_consented_memory(store, owner, sentence, key, client):
    from uuid import uuid4

    alert_id = "alert_test_" + uuid4().hex
    result, _ = store.claim_confirmation(owner, alert_id, "normal", True, bool(sentence), "test")
    placed = await write_placed_memory(store, owner, sentence, key, client, alert_id=alert_id)
    if key and sentence:
        store.finish_memory(owner, result, placed.sentence, memory_id=placed.memory_id,
                            source=placed.source, assistant_id=placed.assistant_id, memory_status=placed.status)
    return placed


ASSISTANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ASSISTANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
KEY = "synthetic-test-key"
STREAMING = "The demo user explicitly confirmed a streaming alert as normal. Recheck future evidence."
FITNESS = (
    "The demo user explicitly confirmed a fitness_subscription alert as normal. "
    "Recheck future evidence."
)


def _sentence(transaction_id: str) -> str:
    rows = load_transactions()
    tx = next(row for row in rows if row.id == transaction_id)
    sentence = memory_sentence(tx, "normal", True, True)
    assert sentence is not None
    return sentence


def test_approved_sentence_rejects_raw_customer_data():
    assert approved_memory(_sentence("txn_syn_004"))
    leaked = STREAMING + " StreamWave acct_demo_a1 4111111111111111"
    assert not approved_memory(leaked)
    assert memory_sentence(load_transactions()[3], "review", True, True) is None


def test_created_memory_requires_a_real_id():
    parsed = parse_created({"memory_id": "mem_remote_1", "content": STREAMING})
    assert parsed.id == "mem_remote_1" and parsed.content == STREAMING
    for body in ({}, {"memory_id": ""}, {"memory_id": "mem bad"}, {"id": 12}, {"memory_id": "a", "id": "b"}):
        try:
            parse_created(body)
        except MemoryCallError as exc:
            assert str(exc) == "invalid_response"
        else:
            raise AssertionError(body)
    page = parse_search({
        "memories": [{"id": "mem_remote_1", "content": STREAMING, "score": 0.91,
                      "created_at": "2026-10-17T00:00:00Z"}],
        "total_count": 1,
    })
    assert page.total_count == 1 and page.memories[0].score == 0.91
    try:
        parse_search({"memories": []})
    except MemoryCallError as exc:
        assert str(exc) == "invalid_response"
    else:
        raise AssertionError("search without total_count was accepted")


def test_missing_key_and_unsafe_content_make_no_request():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("provider was called")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            try:
                await add_memory(ASSISTANT_A, "Jane Doe acct_demo_a1", KEY, client=client)
            except MemoryCallError as exc:
                assert str(exc) == "unsafe_content"
            else:
                raise AssertionError("raw content was accepted")
            try:
                await add_memory(ASSISTANT_A, STREAMING, "  ", client=client)
            except MemoryCallError as exc:
                assert str(exc) == "missing_key"
            else:
                raise AssertionError("missing key was ignored")

    asyncio.run(run())


def test_auth_rate_limit_and_timeout_expose_only_codes():
    """401, 429, and transport errors stay codes. Provider bodies are not kept."""

    def handler(status):
        def respond(_request: httpx.Request) -> httpx.Response:
            if status == "timeout":
                raise httpx.ReadTimeout("secret timeout text")
            return httpx.Response(status, json={"detail": "secret-body"})
        return respond

    async def run():
        found = {}
        for status, expected in ((401, "rejected"), (429, "rejected"), (503, "request_failed"),
                                 ("timeout", "request_failed")):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler(status))) as client:
                try:
                    await list_memories(ASSISTANT_A, KEY, client=client)
                except MemoryCallError as exc:
                    found[status] = str(exc)
                else:
                    found[status] = "accepted"
        return found

    found = asyncio.run(run())
    assert found == {401: "rejected", 429: "rejected", 503: "request_failed", "timeout": "request_failed"}
    assert all("secret" not in code for code in found.values())


def test_rate_limit_marks_memory_failed_not_live(tmp_path):
    store = Store(tmp_path / "rate.db")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/assistants":
            return httpx.Response(200, json={
                "name": ASSISTANT_NAME, "assistant_id": ASSISTANT_A,
                "created_at": "2026-10-17T00:00:00Z",
            })
        if request.method == "GET":
            return httpx.Response(200, json={"memories": [], "total_count": 0})
        return httpx.Response(429, json={"detail": "secret-body"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await write_consented_memory(store, "owner-rate", STREAMING, KEY, client)

    placed = asyncio.run(run())
    assert placed.status == "failed" and placed.outcome == "degraded"
    assert placed.source == "local-fallback"
    assert store.list_memories("owner-rate")[0].source == "local-fallback"
    with store.connect() as db:
        state = db.execute("SELECT state FROM memory_jobs WHERE owner=?",
                           ("owner-rate",)).fetchone()["state"]
    assert state == "failed"


def test_add_get_search_delete_and_provider_failure():
    calls: list[tuple[str, str]] = []
    added = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        body = json.loads(request.content or b"{}")
        text = request.content.decode()
        assert request.headers["X-API-Key"] == KEY
        assert KEY not in text
        if request.method == "POST" and request.url.path.endswith("/memories"):
            added["count"] += 1
            if added["count"] > 1:
                return httpx.Response(503, json={"detail": "secret-body"})
            assert set(body) == {"content"}
            assert body["content"] == STREAMING
            for forbidden in ("StreamWave", "acct_demo_a1", "4111111111111111", "txn_syn_004"):
                assert forbidden not in text
            return httpx.Response(201, json={"memory_id": "mem_remote_1"})
        if request.method == "GET" and request.url.path.endswith("/mem_remote_1"):
            return httpx.Response(200, json={
                "id": "mem_remote_1", "content": STREAMING, "metadata": None,
                "score": None, "created_at": "2026-10-17T00:00:00Z", "updated_at": None,
            })
        if request.method == "POST" and request.url.path.endswith("/search"):
            assert body == {"query": "confirmed a streaming alert as normal", "limit": 5}
            return httpx.Response(200, json={
                "memories": [{"id": "mem_remote_1", "content": STREAMING, "score": 0.8,
                              "created_at": "2026-10-17T00:00:00Z"}],
                "total_count": 1,
            })
        if request.method == "DELETE" and request.url.path.endswith("/mem_remote_1"):
            return httpx.Response(200, json={"success": True, "message": "deleted"})
        return httpx.Response(503, json={"detail": "secret-body"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            created = await add_memory(ASSISTANT_A, STREAMING, KEY, client=client)
            loaded = await get_memory(ASSISTANT_A, created.id, KEY, client=client)
            found = await search_memories(
                ASSISTANT_A, "confirmed a streaming alert as normal", KEY, client=client)
            removed = await delete_memory(ASSISTANT_A, created.id, KEY, client=client)
            try:
                await add_memory(ASSISTANT_A, STREAMING, KEY, client=client)
            except MemoryCallError as exc:
                failure = str(exc)
            else:
                raise AssertionError("provider failure was treated as success")
        return created, loaded, found, removed, failure

    created, loaded, found, removed, failure = asyncio.run(run())
    assert created.id == "mem_remote_1"
    assert loaded.content == STREAMING and loaded.score is None
    assert found.memories[0].content == STREAMING and found.total_count == 1
    assert removed == "deleted"
    assert failure == "request_failed"
    assert "secret-body" not in failure
    assert ("DELETE", f"/api/assistants/{ASSISTANT_A}/memories/mem_remote_1") in calls


def test_invalid_add_is_not_kept_as_a_second_copy():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200, json={"success": True, "message": "deleted"})
        return httpx.Response(201, json={"memory_id": "mem_remote_1", "content": 5})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            try:
                await add_memory(ASSISTANT_A, STREAMING, KEY, client=client)
            except MemoryCallError as exc:
                return str(exc)
        return "accepted"

    assert asyncio.run(run()) == "invalid_response"


def test_delete_false_and_missing_remote_are_distinct():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/mem_false"):
            return httpx.Response(200, json={"success": False, "message": "still there"})
        return httpx.Response(404, json={"detail": "gone"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            try:
                await delete_memory(ASSISTANT_A, "mem_false", KEY, client=client)
            except MemoryCallError as exc:
                refused = str(exc)
            absent = await delete_memory(ASSISTANT_A, "mem_missing", KEY, client=client)
        return refused, absent

    refused, absent = asyncio.run(run())
    assert refused == "not_deleted" and absent == "already_absent"


def test_users_get_isolated_assistants_and_sqlite_fallback(tmp_path):
    store = Store(tmp_path / "memory.db")
    created: list[str] = []
    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/assistants":
            body = json.loads(request.content)
            assert body["name"] == ASSISTANT_NAME
            text = request.content.decode()
            for forbidden in ("owner-a", "owner-b", "StreamWave", "acct_", KEY):
                assert forbidden not in text
            assistant_id = ASSISTANT_B if created else ASSISTANT_A
            created.append(assistant_id)
            return httpx.Response(200, json={
                "name": body["name"], "assistant_id": assistant_id,
                "created_at": "2026-10-17T00:00:00Z",
            })
        if request.method == "POST" and request.url.path.endswith("/memories"):
            posts.append(request.url.path)
            body = json.loads(request.content)
            memory_id = "mem_owner_b" if ASSISTANT_B in request.url.path else "mem_owner_a"
            return httpx.Response(201, json={"memory_id": memory_id, "content": body["content"]})
        if request.method == "GET" and request.url.path.endswith("/memories"):
            if ASSISTANT_A in request.url.path:
                rows = [{"id": "mem_owner_a", "content": STREAMING}]
            else:
                rows = [{"id": "mem_owner_b", "content": FITNESS}]
            return httpx.Response(200, json={"memories": rows, "total_count": len(rows)})
        return httpx.Response(500, json={"detail": "unexpected"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await write_consented_memory(store, "owner-a", STREAMING, KEY, client)
            second = await write_consented_memory(store, "owner-b", FITNESS, KEY, client)
            again = await write_consented_memory(store, "owner-a", None, KEY, client)
            local = await write_consented_memory(store, "owner-a", STREAMING, "", client)
            owner_a, mode_a = await consented_summaries(store, "owner-a", KEY, client)
            owner_b, mode_b = await consented_summaries(store, "owner-b", KEY, client)
        return first, second, again, local, owner_a, mode_a, owner_b, mode_b

    first, second, again, local, owner_a, mode_a, owner_b, mode_b = asyncio.run(run())
    assert first.source == "backboard" and first.memory_id == "mem_owner_a"
    assert second.memory_id == "mem_owner_b" and second.assistant_id == ASSISTANT_B
    assert first.assistant_id != second.assistant_id
    assert again.sentence is None and again.outcome is None
    assert local.source == "local-fallback" and local.status == "written" and local.outcome is None
    assert owner_a == [STREAMING] and FITNESS not in owner_a and mode_a == "backboard-live"
    assert owner_b == [FITNESS] and mode_b == "backboard-live"
    assert posts == [f"/api/assistants/{ASSISTANT_A}/memories",
                     f"/api/assistants/{ASSISTANT_B}/memories"]
    assert created == [ASSISTANT_A, ASSISTANT_B]


def test_old_sqlite_memory_remains_local_fallback(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE memories (memory_id TEXT PRIMARY KEY, owner TEXT, summary TEXT, "
            "created_at TEXT)")
        db.execute("INSERT INTO memories VALUES (?,?,?,?)",
                   ("mem_old", "demo-user-001", STREAMING, "2026-10-17T00:00:00+00:00"))
    store = Store(path)
    rows = store.list_memories("demo-user-001")
    assert len(rows) == 1
    assert rows[0].source == "local-fallback" and rows[0].summary == STREAMING
    assert store.assistant_id("demo-user-001") is None


def test_provider_failure_keeps_one_local_sentence(tmp_path):
    store = Store(tmp_path / "fallback.db")
    store.confirm("demo-user-001", "alert_old", "normal", True, FITNESS, "rid")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/assistants":
            return httpx.Response(200, json={
                "name": ASSISTANT_NAME, "assistant_id": ASSISTANT_A,
                "created_at": "2026-10-17T00:00:00Z",
            })
        return httpx.Response(503, json={"detail": "secret-body"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            failed = await write_consented_memory(store, "demo-user-001", STREAMING, KEY, client)
            listed, mode = await consented_summaries(store, "demo-user-001", KEY, client)
        return failed, listed, mode

    failed, _listed, mode = asyncio.run(run())
    job = store.memory_job("demo-user-001", memory_id=failed.memory_id)
    saved = store.replay_confirmation("demo-user-001", job["alert_id"], "normal", True, "rid")
    rows = store.list_memories("demo-user-001")
    assert failed.status == "failed" and failed.source == "local-fallback"
    assert saved.memory_status == "failed"
    assert mode == "degraded"
    assert {row.summary for row in rows} == {FITNESS, STREAMING}
    assert {row.source for row in rows} == {"local-fallback"}
    assert all(row.source != "backboard" for row in rows)


def test_malformed_memory_pages_fail_closed():
    from app.services.ai.backboard_client import parse_list

    malformed = [{}, {"memories": []}, {"memories": [], "total_count": -1},
                 {"memories": [{"id": "mem_safe", "content": STREAMING, "score": 10 ** 400}],
                  "total_count": 1}]
    for value in malformed:
        try:
            parse_list(value)
        except MemoryCallError:
            continue
        raise AssertionError("Malformed memory page was accepted")


def test_delete_during_delayed_create_ack_never_restores_memory(tmp_path):
    from app.services.ai.memory_sync import remove_remote_memory

    store = Store(tmp_path / "delete-race.db")
    store.save_assistant("owner", ASSISTANT_A)
    receipt, _ = store.claim_confirmation("owner", "alert", "normal", True, True, "request")
    remote = []

    async def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"memories": list(remote), "total_count": len(remote)})
        if request.method == "DELETE":
            remote.clear()
            return httpx.Response(200, json={"success": True, "message": "deleted"})
        remote.append({"id": "delayed_ack", "content": STREAMING})
        local_id = store.memory_job("owner", alert_id="alert")["local_id"]
        await remove_remote_memory(store, "owner", local_id, KEY, client)
        assert store.delete_memory("owner", local_id)
        return httpx.Response(201, json={"memory_id": "delayed_ack", "content": STREAMING})

    async def run():
        nonlocal client
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            placed = await write_placed_memory(store, "owner", STREAMING, KEY, client, alert_id="alert")
            store.finish_memory("owner", receipt, placed.sentence, memory_id=placed.memory_id,
                                source=placed.source, assistant_id=placed.assistant_id,
                                memory_status=placed.status)

    client = None
    asyncio.run(run())
    assert not remote and store.list_memories("owner") == []
    assert store.memory_job("owner", alert_id="alert")["state"] == "deleted"


def test_same_sentence_claim_precedes_baseline_read_across_stores(tmp_path):
    filename = tmp_path / "overlap.db"
    store, second = Store(filename), Store(filename)
    store.save_assistant("owner", ASSISTANT_A)
    for alert in ("first", "second"):
        store.claim_confirmation("owner", alert, "normal", True, True, "request")
    remote, posts = [], []
    nested = False

    async def handler(request):
        nonlocal nested
        if request.method == "GET":
            snapshot = list(remote)
            if not nested:
                nested = True
                await write_placed_memory(second, "owner", STREAMING, KEY, client, alert_id="second")
            return httpx.Response(200, json={"memories": snapshot, "total_count": len(snapshot)})
        posts.append(request)
        if len(posts) == 1:
            remote.append({"id": "other_job", "content": STREAMING})
            return httpx.Response(201, json={"memory_id": "other_job", "content": STREAMING})
        raise httpx.ReadTimeout("Synthetic uncertain write")

    async def run():
        nonlocal client
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await write_placed_memory(store, "owner", STREAMING, KEY, client, alert_id="first")

    client = None
    asyncio.run(run())
    assert len(posts) == 1
    job = store.memory_job("owner", alert_id="second")
    assert job is None or job["remote_id"] is None
