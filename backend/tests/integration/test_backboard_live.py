"""Opt-in live Backboard memory check. Default pytest does not call the provider.

Set BACKBOARD_LIVE_TEST=1 to create two temporary assistants, store one approved
category sentence on each, check reuse and isolation, then delete them.
The key is read from backend/.env and is never printed.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app.core.store import Store
from app.services.ai.backboard_client import (
    API_ROOT, MemoryCallError, delete_memory, get_memory, list_memories,
)
from app.services.ai.memory_sync import ensure_assistant, write_consented_memory

pytestmark = [pytest.mark.live_network, pytest.mark.skipif(
    os.environ.get("BACKBOARD_LIVE_TEST") != "1",
    reason="Set BACKBOARD_LIVE_TEST=1 to spend Backboard credits on a live memory check.",
)]

BACKEND = Path(__file__).resolve().parents[2]
OWNER_A = "trustledger_backboard_test_user"
OWNER_B = "trustledger_backboard_test_user_b"
STREAMING = "The demo user explicitly confirmed a streaming alert as normal. Recheck future evidence."
FITNESS = (
    "The demo user explicitly confirmed a fitness_subscription alert as normal. "
    "Recheck future evidence."
)
CHILD = r"""
import asyncio, os, sys
sys.path.insert(0, sys.argv[1])
from app.core.config import Settings
from app.services.ai.backboard_client import MemoryCallError, get_memory, list_memories
import httpx

async def main():
    key = Settings().backboard_api_key.get_secret_value()
    assistant, memory, sentence = os.environ["TL_ASSISTANT"], os.environ["TL_MEMORY"], os.environ["TL_SENTENCE"]
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            loaded = await get_memory(assistant, memory, key, client=client)
            page = await list_memories(assistant, key, client=client)
    except MemoryCallError as exc:
        print("persist", str(exc))
        return
    match = loaded.content == sentence and any(
        row.id == memory and row.content == sentence for row in page.memories)
    print("persist", "True" if match else "False")

asyncio.run(main())
"""


def test_live_assistants_are_isolated_and_reused(tmp_path):
    asyncio.run(_live(tmp_path))


async def _balance(client, key):
    response = await client.get(f"{API_ROOT}/billing/balance", headers={"X-API-Key": key})
    if response.status_code != 200:
        raise AssertionError(f"balance_status {response.status_code}")
    body = response.json()
    if not isinstance(body, dict):
        raise AssertionError("balance_body")
    return body.get("balance_usd"), body.get("auto_reload_enabled")


async def _place(store, owner, alert_id, sentence, key, client):
    receipt, created = store.claim_confirmation(owner, alert_id, "normal", True, True, alert_id)
    if not created:
        raise AssertionError(f"claim_existed {owner}")
    placed = await write_consented_memory(
        store, owner, sentence, key, client, alert_id=alert_id)
    finished = store.finish_memory(
        owner, receipt, placed.sentence, memory_id=placed.memory_id, source=placed.source,
        assistant_id=placed.assistant_id, memory_status=placed.status)
    return placed, finished


async def _discard(client, key, assistant_id, memory_ids):
    memory_codes = []
    for memory_id in memory_ids:
        if not memory_id:
            continue
        try:
            memory_codes.append(await delete_memory(assistant_id, memory_id, key, client=client))
        except MemoryCallError as exc:
            memory_codes.append(str(exc))
    response = await client.delete(
        f"{API_ROOT}/assistants/{assistant_id}", headers={"X-API-Key": key})
    return response.status_code, memory_codes


async def _live(tmp_path):
    from app.core.config import Settings

    key = Settings().backboard_api_key.get_secret_value()
    if not key.strip():
        raise AssertionError("missing_key")
    store = Store(tmp_path / "live.db")
    posts = []
    created_ids = []

    async def on_request(request):
        if request.method != "POST":
            return
        posts.append(request.url.path)
        if not request.url.path.endswith("/memories"):
            return
        text = json.loads(request.content or b"{}").get("content", "")
        if not isinstance(text, str) or key in text or "$" in text:
            raise AssertionError("unsafe memory body")
        for forbidden in ("Starbucks", "Tech Harbor", "StreamWave", "FitFlow", "acct_"):
            if forbidden in text:
                raise AssertionError("unsafe memory body")

    async def on_response(response):
        path = response.request.url.path
        if response.request.method == "POST" and path == "/api/assistants" and response.status_code == 200:
            await response.aread()
            assistant_id = response.json().get("assistant_id")
            if isinstance(assistant_id, str):
                created_ids.append(assistant_id)

    report = {}
    async with httpx.AsyncClient(
        timeout=20.0, event_hooks={"request": [on_request], "response": [on_response]},
    ) as client:
        try:
            report["balance_before"], report["auto_reload_before"] = await _balance(client, key)
            first, first_row = await _place(store, OWNER_A, "alert_live_a", STREAMING, key, client)
            second, second_row = await _place(store, OWNER_B, "alert_live_b", FITNESS, key, client)
            assistant_a, assistant_b = first.assistant_id, second.assistant_id
            if not assistant_a or not assistant_b or assistant_a == assistant_b:
                raise AssertionError("assistant_isolation")
            reused = await ensure_assistant(store, OWNER_A, key, client)
            if reused != assistant_a:
                raise AssertionError("assistant_reuse")
            post_count = len(posts)
            again = await write_consented_memory(
                store, OWNER_A, STREAMING, key, client, alert_id="alert_live_a")
            if again.memory_id != first.memory_id or len(posts) != post_count:
                raise AssertionError("duplicate_write")
            replay = store.replay_confirmation(OWNER_B, "alert_live_b", "normal", True, "replay")
            if replay is None or replay.memory_status != "written":
                raise AssertionError("replay")
            page_a = await list_memories(assistant_a, key, client=client)
            page_b = await list_memories(assistant_b, key, client=client)
            text_a = {row.content for row in page_a.memories}
            text_b = {row.content for row in page_b.memories}
            if text_a != {STREAMING} or text_b != {FITNESS}:
                raise AssertionError("remote_isolation")
            loaded = await get_memory(assistant_b, second.memory_id, key, client=client)
            if loaded.content != FITNESS:
                raise AssertionError("get_mismatch")
            from app.services.ai.memory_sync import consented_summaries
            local_a, mode_a = await consented_summaries(store, OWNER_A, key, client)
            local_b, mode_b = await consented_summaries(store, OWNER_B, key, client)
            if local_a != [STREAMING] or local_b != [FITNESS] or mode_a != "backboard-live" or mode_b != "backboard-live":
                raise AssertionError("app_isolation")
            rows_a = store.list_memories(OWNER_A)
            rows_b = store.list_memories(OWNER_B)
            if rows_a[0].source != "backboard" or rows_b[0].source != "backboard":
                raise AssertionError("source_label")
            if first_row.memory_status != "written" or second_row.memory_status != "written":
                raise AssertionError("memory_status")
            child = subprocess.run(
                [sys.executable, "-c", CHILD, str(BACKEND)],
                cwd=BACKEND, capture_output=True, text=True, timeout=40,
                env={**os.environ, "TL_ASSISTANT": assistant_b, "TL_MEMORY": second.memory_id,
                     "TL_SENTENCE": FITNESS}, check=False)
            leaked = key in child.stdout or key in child.stderr
            safe_err = child.stderr.replace(key, "[redacted]")
            Path("/tmp/tl-live-child.err").write_text(safe_err)
            if leaked or child.returncode != 0 or child.stdout.strip() != "persist True":
                raise AssertionError(f"persist_process {child.returncode}")
            try:
                await list_memories(assistant_b, "invalid-backboard-key", client=client)
            except MemoryCallError as exc:
                invalid = str(exc)
            else:
                invalid = "accepted"
            if invalid != "rejected":
                raise AssertionError(f"invalid_key {invalid}")
            report.update({
                "creates": posts.count("/api/assistants"),
                "memory_posts": sum(path.endswith("/memories") for path in posts),
                "posts": posts,
                "isolation": True,
                "reuse": True,
                "persist": True,
                "invalid_key": invalid,
                "source": "backboard",
            })
        finally:
            discarded = []
            for assistant_id in dict.fromkeys(created_ids):
                memory_ids = []
                try:
                    page = await list_memories(assistant_id, key, client=client)
                    memory_ids = [row.id for row in page.memories]
                except MemoryCallError:
                    memory_ids = []
                status, memory_codes = await _discard(client, key, assistant_id, memory_ids)
                discarded.append({"status": status, "memories": memory_codes})
            report["discarded"] = discarded
            try:
                report["balance_after"], report["auto_reload_after"] = await _balance(client, key)
            except AssertionError as exc:
                report["balance_after"] = str(exc)
            Path("/tmp/tl-live-result.json").write_text(json.dumps(report))
    if report.get("isolation") is not True:
        raise AssertionError("live_memory_failed")
    if any(item["status"] != 200 for item in report["discarded"]):
        raise AssertionError("cleanup_failed")
    if report["creates"] != 2 or report["memory_posts"] != 2:
        raise AssertionError("call_count")
