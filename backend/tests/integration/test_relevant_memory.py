"""Level 2 uses point reads, consent references and durable deletion jobs; no network."""

import json
import sqlite3
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.main import create_app
from app.services.ai.memory_policy import memory_sentence
from app.services.ai.relevant_memory import MAX_CHECKS

URL = "/api/v1/transactions/txn_syn_003/relevant-memories"
ASSISTANT = str(uuid4())
OTHER = str(uuid4())


def saved(client, source="backboard", owner=None, alert="alert_txn_syn_004", consent=True):
    store = client.app.state.store
    owner = owner or client.app.state.settings.demo_user_id
    tx = store.list_transactions(client.app.state.settings.demo_user_id)
    tx = next(t for t in tx if t.id == "txn_syn_004")
    sentence = memory_sentence(tx, "normal", True, True)
    result = store.confirm(owner, alert, "normal", consent, sentence if consent else None, "test")
    if result.memory_id and source == "backboard":
        store.save_assistant(owner, ASSISTANT)
        with store.connect() as db:
            db.execute(
                "UPDATE memories SET source='backboard',assistant_id=? WHERE owner=? AND memory_id=?",
                (ASSISTANT, owner, result.memory_id),
            )
    return result, sentence


def remote(client, handler):
    calls = []

    def wrapped(request):
        assert request.method == "GET"
        assert request.headers["x-api-key"] == "test-key"
        calls.append(request.url.path)
        return handler(request)

    client.app.state.settings.backboard_api_key = SecretStr("test-key")
    client.app.state.backboard_transport = httpx.MockTransport(wrapped)
    return calls


def record(mid, sentence):
    return httpx.Response(200, json={"id": mid, "content": sentence})


def test_empty_and_unknown_transaction_do_not_call_remote(client):
    calls = remote(client, lambda r: pytest.fail("no request expected"))
    body = client.get(URL).json()
    assert body == {
        "memories": [],
        "retrieval_mode": "local_fallback",
        "checked_at": None,
        "failure": None,
    }
    assert client.get(URL.replace("txn_syn_003", "missing")).status_code == 404
    assert calls == []


def test_second_similar_transaction_remote_verified_without_analysis_changes(client):
    receipt, sentence = saved(client)
    before = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_003"}).json()
    calls = remote(client, lambda r: record(receipt.memory_id, sentence))
    body = client.get(URL).json()
    assert body["retrieval_mode"] == "remote_verified" and body["checked_at"]
    assert body["memories"][0]["verification"] == "remote_verified"
    assert body["memories"][0]["memory_id"] == receipt.memory_id
    assert len(calls) == 1 and receipt.memory_id in calls[0]
    assert client.get(URL.replace("txn_syn_003", "txn_syn_005")).json()["memories"] == []
    after = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_003"}).json()
    before.pop("request_id")
    after.pop("request_id")
    assert before == after


@pytest.mark.parametrize(
    "case", ["missing", "content", "identity", "timeout", "401", "429", "503", "malformed"]
)
def test_remote_outcomes_are_truthful(client, case):
    receipt, sentence = saved(client)

    def handler(request):
        if case == "missing":
            return httpx.Response(404)
        if case == "content":
            return record(receipt.memory_id, "unapproved merchant content")
        if case == "identity":
            return record("wrong-memory", sentence)
        if case == "timeout":
            raise httpx.ReadTimeout("SECRET upstream key")
        if case == "malformed":
            return httpx.Response(200, json={"memories": []})
        return httpx.Response(int(case), json={"secret": "SECRET"})

    remote(client, handler)
    response = client.get(URL)
    assert response.status_code == 200 and "SECRET" not in response.text
    body = response.json()
    if case == "missing":
        assert (
            body["retrieval_mode"] == "remote_verified"
            and body["memories"] == []
            and body["checked_at"]
        )
    elif case == "content":
        assert (
            body["failure"] == "content_mismatch"
            and body["memories"] == []
            and body["checked_at"] is None
        )
    else:
        assert body["retrieval_mode"] == "local_fallback" and body["checked_at"] is None
        assert body["memories"][0]["verification"] == "unverified"


def test_consent_owner_and_orphan_filter(client):
    saved(client, owner="other-owner")
    saved(client, consent=False)
    calls = remote(client, lambda r: pytest.fail("no eligible rows"))
    assert client.get(URL).json()["memories"] == [] and calls == []


@pytest.mark.parametrize("case", ["no_key", "no_assistant", "local"])
def test_fallback_provenance(client, case):
    saved(client, source="local-fallback" if case == "local" else "backboard")
    if case == "no_assistant":
        client.app.state.settings.backboard_api_key = SecretStr("test-key")
        with client.app.state.store.connect() as db:
            db.execute("DELETE FROM assistants")
    body = client.get(URL).json()
    assert body["retrieval_mode"] == "local_fallback" and body["checked_at"] is None
    assert body["memories"][0]["verification"] == (
        "local_only" if case == "local" else "unverified"
    )
    assert (
        body["failure"]
        == {"no_key": "missing_key", "no_assistant": "missing_assistant", "local": None}[case]
    )


def test_bounded_point_reads_ignore_list_pagination_and_mark_partial(client):
    for index in range(MAX_CHECKS + 1):
        saved(client, alert=f"alert-{index}")
    rows = client.app.state.store.relevant_memory_rows("demo-user-001")
    lookup = {r["memory_id"]: r["summary"] for r in rows}
    calls = remote(
        client, lambda r: record(r.url.path.split("/")[-1], lookup[r.url.path.split("/")[-1]])
    )
    body = client.get(URL).json()
    assert len(calls) == MAX_CHECKS and all("/memories/" in path for path in calls)
    assert body["failure"] == "verification_limit" and body["retrieval_mode"] == "local_fallback"
    assert sum(m["verification"] == "remote_verified" for m in body["memories"]) == MAX_CHECKS
    assert body["checked_at"] is None


def test_deleted_during_read_cannot_reappear(client):
    receipt, sentence = saved(client)

    def handler(r):
        client.app.state.store.delete_memory("demo-user-001", receipt.memory_id)
        return record(receipt.memory_id, sentence)

    remote(client, handler)
    assert client.get(URL).json()["memories"] == []


def deleted_job(client):
    store = client.app.state.store
    owner = "demo-user-001"
    receipt, sentence = saved(client, source="local-fallback")
    store.save_assistant(owner, ASSISTANT)
    local = store.prepare_memory_job(owner, receipt.alert_id, ASSISTANT, sentence)
    store.record_memory_baseline(owner, receipt.alert_id, [])
    store.update_memory_job(owner, receipt.alert_id, "confirmed", "remote-test")
    store.finish_memory(
        owner,
        receipt,
        sentence,
        memory_id="remote-test",
        source="backboard",
        assistant_id=ASSISTANT,
        memory_status="written",
    )
    # Remove helper's first local row, preserving the canonical job-backed row.
    store.delete_memory(owner, receipt.memory_id)
    return local, sentence


@pytest.mark.parametrize("state", ["absent", "present", "error"])
def test_delete_204_is_separate_from_fresh_verification_and_survives_restart(client, state):
    _, sentence = deleted_job(client)
    requests = []

    def handler(r):
        requests.append(r.method)
        if r.method == "DELETE":
            return httpx.Response(200, json={"success": True, "message": "deleted"})
        if state == "error":
            return httpx.Response(503)
        return httpx.Response(404) if state == "absent" else record("remote-test", sentence)

    client.app.state.settings.backboard_api_key = SecretStr("test-key")
    client.app.state.backboard_transport = httpx.MockTransport(handler)
    path = "/api/v1/memories/remote-test"
    response = client.delete(path)
    assert response.status_code == 204 and not response.content
    assert requests == ["DELETE"]
    with TestClient(create_app(client.app.state.settings)) as restarted:
        restarted.app.state.backboard_transport = httpx.MockTransport(handler)
        body = restarted.get(path + "/deletion-verification").json()
        assert body["status"] == ("unverified" if state == "error" else state)
        assert bool(body["checked_at"]) == (state != "error")
        assert restarted.get(URL).json()["memories"] == []
    assert requests == ["DELETE", "GET"]
    assert client.get("/api/v1/memories/other-id/deletion-verification").status_code == 404


def test_storage_failure_returns_unavailable(client, monkeypatch):
    def broken(owner):
        raise sqlite3.OperationalError("private database")

    monkeypatch.setattr(client.app.state.store, "relevant_memory_rows", broken)
    body = client.get(URL).json()
    assert body["retrieval_mode"] == "unavailable" and body["failure"] == "storage_unavailable"


def test_deletion_before_delete_is_not_verified(client):
    receipt, _ = saved(client)
    body = client.get("/api/v1/memories/" + receipt.memory_id + "/deletion-verification").json()
    assert body["status"] == "unverified" and body["failure"] == "deletion_not_completed"


def test_openapi_examples_match_response_models(client):
    from pathlib import Path
    import yaml
    from jsonschema import Draft202012Validator, FormatChecker

    contract = yaml.safe_load(
        (Path(__file__).resolve().parents[3] / "contracts/internal-api.openapi.yaml").read_text()
    )
    for name in ["RelevantMemories", "DeletionVerification"]:
        schema = contract["components"]["schemas"][name]
        Draft202012Validator(
            {**schema, "components": contract["components"]}, format_checker=FormatChecker()
        ).validate(schema["example"])
    assert json.loads(client.get(URL).text)["retrieval_mode"] == "local_fallback"


def test_partial_success_has_per_memory_status_and_no_full_verification(client):
    first, sentence = saved(client, alert="first")
    second, _ = saved(client, alert="second")

    def handler(request):
        return (
            record(first.memory_id, sentence)
            if request.url.path.endswith(first.memory_id)
            else httpx.Response(503)
        )

    remote(client, handler)
    body = client.get(URL).json()
    assert body["retrieval_mode"] == "local_fallback" and body["checked_at"] is None
    assert {m["memory_id"]: m["verification"] for m in body["memories"]} == {
        first.memory_id: "remote_verified",
        second.memory_id: "unverified",
    }


def test_other_owner_cannot_verify_known_deletion_id(client):
    _, sentence = deleted_job(client)
    client.app.state.store.update_memory_job(
        "demo-user-001", "alert_txn_syn_004", "deleted", "remote-test"
    )
    client.app.state.store.delete_memory("demo-user-001", "remote-test")
    client.app.state.settings.demo_user_id = "other-owner"
    assert client.get("/api/v1/memories/remote-test/deletion-verification").status_code == 404


def test_remote_missing_is_not_replaced_with_stale_local_content(client):
    receipt, sentence = saved(client)
    calls = remote(client, lambda r: record(receipt.memory_id, sentence))
    assert client.get(URL).json()["memories"]
    client.app.state.backboard_transport = httpx.MockTransport(lambda r: httpx.Response(404))
    body = client.get(URL).json()
    assert body["retrieval_mode"] == "remote_verified" and not body["memories"]
    assert len(calls) == 1


def test_verification_deadline_returns_safe_local_context(client, monkeypatch):
    import asyncio
    from app.services.ai import relevant_memory

    saved(client)
    client.app.state.settings.backboard_api_key = SecretStr("test-key")
    monkeypatch.setattr(relevant_memory, "VERIFICATION_SECONDS", 0.01)

    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(relevant_memory, "memory_presence", slow)
    body = client.get(URL).json()
    assert body["failure"] == "provider_error" and body["checked_at"] is None
    assert body["memories"][0]["verification"] == "unverified"


def test_null_200_is_not_verified_absence(client):
    saved(client)
    remote(
        client,
        lambda r: httpx.Response(200, content="null", headers={"content-type": "application/json"}),
    )
    body = client.get(URL).json()
    assert body["failure"] == "provider_error" and body["retrieval_mode"] == "local_fallback"
    assert body["checked_at"] is None


def test_contract_failure_enums_match_actual_schemas():
    from pathlib import Path
    import yaml
    from app.schemas.relevant_memory import RelevantMemories, DeletionVerification

    contract = yaml.safe_load(
        (Path(__file__).resolve().parents[3] / "contracts/internal-api.openapi.yaml").read_text()
    )
    for model in [RelevantMemories, DeletionVerification]:
        actual = model.model_json_schema()["properties"]
        documented = contract["components"]["schemas"][model.__name__]["properties"]
        assert actual["failure"] == documented["failure"]
        if model is DeletionVerification:
            assert actual["status"] == documented["status"]


def test_revoked_consent_row_is_excluded_without_provider_read(client):
    saved(client)
    with client.app.state.store.connect() as db:
        db.execute("UPDATE confirmations SET consent=0 WHERE owner='demo-user-001'")
    calls = remote(client, lambda r: pytest.fail("revoked consent cannot be retrieved"))
    assert client.get(URL).json()["memories"] == []
    assert calls == []


def test_remote_retrieval_survives_database_restart(client):
    receipt, sentence = saved(client)
    client.app.state.settings.backboard_api_key = SecretStr("test-key")
    with TestClient(create_app(client.app.state.settings)) as restarted:
        restarted.app.state.backboard_transport = httpx.MockTransport(
            lambda r: record(receipt.memory_id, sentence)
        )
        body = restarted.get(URL).json()
        assert body["retrieval_mode"] == "remote_verified"
        assert body["memories"][0]["memory_id"] == receipt.memory_id
