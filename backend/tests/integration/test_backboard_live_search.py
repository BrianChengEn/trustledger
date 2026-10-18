"""Opt-in Backboard search check for the isolated txn_syn_004 / txn_syn_009 pair.

Default pytest does not call Backboard. Set BACKBOARD_LIVE_SEARCH_TEST=1 to run
the calls below. scripts/check.sh must not set that variable. This test does
not call Jev, Gemini, or Nessie, and it does not open trustledger-demo.db for
the extra row.

Success-path Backboard calls, in order:
1. POST /assistants
2. GET  /assistants/{id}/memories
3. POST /assistants/{id}/memories
4. POST /assistants/{id}/memories/search
5. DELETE /assistants/{id}/memories/{memory_id}
6. POST /assistants/{id}/memories/search
Cleanup, always, and only for the assistant this test created:
7. GET  /assistants/{id}/memories
8. DELETE /assistants/{id}
Measurement, not a memory operation:
9. GET /billing/balance before
10. GET /billing/balance after
"""

import json
import os
from pathlib import Path

import httpx
import pytest

from app.adapters.level2_pair import LATER
from app.services.ai import backboard_client
from app.services.ai.backboard_client import API_ROOT, delete_memory, list_memories, search_memories
from app.services.ai.memory_policy import memory_sentence

pytestmark = [pytest.mark.live_network, pytest.mark.skipif(
    os.environ.get("BACKBOARD_LIVE_SEARCH_TEST") != "1",
    reason="Set BACKBOARD_LIVE_SEARCH_TEST=1 to spend Backboard memory credits.",
)]

STREAMING = memory_sentence(LATER, "normal", True, True)
QUERY = "confirmed a streaming alert as normal"
SCENARIO = [
    "POST /assistants",
    "GET /memories",
    "POST /memories",
    "POST /search",
    "DELETE /memories/",
    "POST /search",
]


def test_live_search_matches_then_forgets_the_similar_alert(tmp_path, monkeypatch):
    import asyncio

    asyncio.run(_live(tmp_path, monkeypatch))


def _label(call: str) -> str:
    method, path = call.split(" ", 1)
    if path == "/assistants":
        return "POST /assistants"
    if path.endswith("/search"):
        return f"{method} /search"
    if method == "DELETE" and "/memories/" in path:
        return "DELETE /memories/"
    if path.endswith("/memories"):
        return f"{method} /memories"
    if method == "DELETE" and path.startswith("/assistants/"):
        return "DELETE /assistants"
    return call


async def _live(tmp_path, monkeypatch):
    from app.adapters.level2_pair import seed_level2_pair
    from app.core.config import Settings
    from app.main import create_app
    from fastapi.testclient import TestClient

    def forbid_paid_provider(*_args, **_kwargs):
        raise AssertionError("Jev or Gemini was called")

    monkeypatch.setattr("app.core.jev.classify", forbid_paid_provider)
    monkeypatch.setattr("app.services.ai.jev_client.classify", forbid_paid_provider)
    key = Settings().backboard_api_key.get_secret_value()
    if not key.strip():
        raise AssertionError("missing_key")
    settings = Settings(
        _env_file=None, database_path=tmp_path / "level2.db", allow_memory_write=True,
        fraud_provider="rules-only", backboard_api_key=key, jev_api_key="",
        gemini_api_key="", nessie_api_key="")
    app = create_app(settings)
    if Path(app.state.store.filename).name == "trustledger-demo.db":
        raise AssertionError("demo_database")
    assert seed_level2_pair(app.state.store) == 19
    calls: list[str] = []
    created: list[str] = []
    original = backboard_client._send

    async def recorded(method, url, api_key, client=None, **kwargs):
        path = url.removeprefix(API_ROOT)
        if "threads" in path or "gemini" in path or "nessie" in path:
            raise AssertionError(f"unexpected_provider {method}")
        calls.append(f"{method} {path}")
        data = await original(method, url, api_key, client, **kwargs)
        if method == "POST" and path == "/assistants" and isinstance(data, dict):
            assistant_id = data.get("assistant_id")
            if isinstance(assistant_id, str):
                created.append(assistant_id)
        return data

    monkeypatch.setattr(backboard_client, "_send", recorded)
    report: dict = {}
    async with httpx.AsyncClient(timeout=20.0) as http:
        try:
            before = await http.get(f"{API_ROOT}/billing/balance", headers={"X-API-Key": key})
            report["balance_before"] = before.json().get("balance_usd") if before.status_code == 200 else None
            with TestClient(app) as live:
                declined = live.post("/api/v1/alerts/alert_txn_syn_005/confirmations",
                                     json={"decision": "normal", "consent_to_memory": False})
                assert declined.status_code == 200
                assert declined.json()["memory_status"] == "not-requested"
                assert calls == []
                absent = live.get("/api/v1/transactions/txn_syn_009/relevant-memory")
                assert absent.status_code == 200
                assert absent.json()["memory_status"] == "no-relevant-memory"
                assert absent.json()["alert_type"] == "duplicate"
                assert calls == []
                saved = live.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                                  json={"decision": "normal", "consent_to_memory": True})
                assert saved.status_code == 200
                memory_id = saved.json()["memory_id"]
                assert saved.json()["memory_status"] == "written"
                found = live.get("/api/v1/transactions/txn_syn_009/relevant-memory").json()
                assert found["memory_status"] == "backboard-live"
                assert found["retrieval"] == "backboard-search"
                assert found["memory_id"] == memory_id
                assert found["summary"] == STREAMING
                assert "StreamWave" not in found["summary"]
                assert found["still_requires_review"] is True
                assert found["alert_type"] == "duplicate" and found["needs_human"] is True
                open_alert = next(row for row in live.get("/api/v1/alerts").json()
                                  if row["transaction_id"] == "txn_syn_009")
                assert open_alert["status"] == "open"
                assert live.delete(f"/api/v1/memories/{memory_id}").status_code == 204
                page = await search_memories(created[0], QUERY, key, limit=5, client=http)
                assert all(row.id != memory_id and row.content != STREAMING for row in page.memories)
                cleared = live.get("/api/v1/transactions/txn_syn_009/relevant-memory").json()
                assert cleared["memory_status"] == "no-relevant-memory"
                assert cleared["memory_id"] is None and cleared["needs_human"] is True
            report["matched"] = True
        finally:
            for assistant_id in dict.fromkeys(created):
                try:
                    page = await list_memories(assistant_id, key, client=http)
                    for row in page.memories:
                        await delete_memory(assistant_id, row.id, key, client=http)
                except Exception as exc:
                    report["cleanup_error"] = type(exc).__name__
                removed = await http.delete(
                    f"{API_ROOT}/assistants/{assistant_id}", headers={"X-API-Key": key})
                calls.append(f"DELETE /assistants/{assistant_id}")
                report["assistant_delete"] = removed.status_code
            after = await http.get(f"{API_ROOT}/billing/balance", headers={"X-API-Key": key})
            report["balance_after"] = after.json().get("balance_usd") if after.status_code == 200 else None
            report["calls"] = [_label(call) for call in calls]
            Path("/tmp/tl-level2-live-search.json").write_text(json.dumps(report))
    if report.get("matched") is not True:
        raise AssertionError("live_search_failed")
    if report.get("assistant_delete") != 200:
        raise AssertionError("cleanup_failed")
    labels = report["calls"]
    assert labels[:6] == SCENARIO
    assert labels[6:] == ["GET /memories", "DELETE /assistants"]
