"""Explicit isolated TEST FIXTURES: actual rules/routes/SQLite + mocked provider HTTP.

No live provider writes. Canonical known-category fixture tests relevance; the Nessie
wire fixture separately proves normalization and the conservative 'other' boundary.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.nessie import NessieClient
from app.api.dependencies import get_transaction_provider
from app.core.config import Settings
from app.core.transactions import SyntheticTransactionProvider
from app.main import create_app
from app.schemas.transaction import Transaction
from app.services.ai.gemini_explanation import template_prose
from app.core.rules import evaluation_outcome

CUSTOMER = "c" * 24
ACCOUNT = "a" * 24


class TestMemoryHTTP:
    __test__ = False

    def __init__(self):
        self.assistant = str(uuid4())
        self.records = {}
        self.writes = []
        self.calls = []
        self.fail = None

    def __call__(self, request):
        self.calls.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "POST" and path.endswith("/assistants"):
            return httpx.Response(
                200,
                json={
                    "assistant_id": self.assistant,
                    "name": "isolated test",
                    "created_at": "2026-10-18",
                },
            )
        if request.method == "POST" and path.endswith("/memories"):
            body = json.loads(request.content)
            assert set(body) == {"content"}
            self.writes.append(body)
            if self.fail == "rejected":
                return httpx.Response(401)
            mid = str(uuid4())
            self.records[mid] = body["content"]
            if self.fail == "timeout":
                raise httpx.ReadTimeout("test-only uncertain write")
            return httpx.Response(201, json={"memory_id": mid, "content": body["content"]})
        if request.method == "GET" and path.endswith("/memories"):
            return httpx.Response(
                200,
                json={
                    "memories": [
                        {"id": mid, "content": content} for mid, content in self.records.items()
                    ],
                    "total_count": len(self.records),
                },
            )
        mid = path.rsplit("/", 1)[-1]
        if request.method == "GET":
            return (
                httpx.Response(200, json={"id": mid, "content": self.records[mid]})
                if mid in self.records
                else httpx.Response(404)
            )
        if request.method == "DELETE":
            if self.fail == "delete":
                return httpx.Response(503)
            self.records.pop(mid, None)
            return httpx.Response(
                200, json={"success": True, "message": "deleted isolated test memory"}
            )
        raise AssertionError("Unexpected mocked provider operation")


@pytest.fixture
def lifecycle(tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        transaction_provider="synthetic",
        database_path=tmp_path / "isolated.db",
        demo_user_id="fixture-owner",
        require_login=True,
        demo_user_passcode="test-login",
        demo_admin_passcode="admin-test",
        backboard_api_key="isolated-fake-key",
        gemini_api_key="test-only-gemini",
        jev_api_key="",
        nessie_api_key="",
        allow_memory_write=True,
    )
    rows = [
        Transaction(
            id=f"txn_fixture_{i}",
            account_token="acct_fixture",
            occurred_at=datetime(2026, 10, 17, i, tzinfo=timezone.utc),
            amount=amount,
            currency="USD",
            direction="debit",
            merchant_display="TEST FIXTURE merchant",
            merchant_category="groceries",
            source="synthetic",
            is_subscription=False,
            kind="purchase",
        )
        for i, amount in [(1, 300), (2, 350)]
    ]
    provider = SyntheticTransactionProvider(rows, "fixture-owner")
    memory = TestMemoryHTTP()
    documents = []

    class MockExplanation:
        def generate(self, document):
            documents.append(document)
            return json.dumps(
                {"stated_alert_type": document["alert_type"], **template_prose(document)}
            )

    def build():
        app = create_app(settings)
        app.dependency_overrides[get_transaction_provider] = lambda: provider
        app.state.backboard_transport = httpx.MockTransport(memory)
        app.state.explanation_transport = MockExplanation()
        return app

    with TestClient(build()) as client:
        assert client.get("/api/v1/transactions").status_code == 401
        assert (
            client.post(
                "/api/v1/auth/login", json={"role": "user", "passcode": "test-login"}
            ).status_code
            == 200
        )
        yield client, memory, documents, build


def without_request(body):
    return {k: v for k, v in body.items() if k != "request_id"}


def test_full_stateful_lifecycle_with_real_rules_and_mocked_remote_persistence(lifecycle):
    client, memory, documents, build = lifecycle
    tx = client.get("/api/v1/transactions").json()[-1]
    assert tx["id"] == "txn_fixture_1"
    before = client.post("/api/v1/analyses", json={"transaction_id": tx["id"]})
    assert before.status_code == 200
    assert before.json()["alert_type"] == "amount_anomaly" and before.json()["needs_human"]
    assert without_request(
        client.post("/api/v1/analyses", json={"transaction_id": tx["id"]}).json()
    ) == without_request(before.json())
    alert = next(a for a in client.get("/api/v1/alerts").json() if a["transaction_id"] == tx["id"])
    assert alert["alert_id"] == "alert_" + tx["id"] and alert["evidence"]
    privacy = client.get("/api/v1/privacy/preview/" + tx["id"]).json()
    assert privacy["safe_payload"]["prior_user_confirmation"] == "unknown"
    path = "/api/v1/alerts/" + alert["alert_id"] + "/confirmations"
    body = {"decision": "normal", "consent_to_memory": True}
    receipt = client.post(path, json=body).json()
    assert receipt["memory_status"] == "written"
    assert len(memory.writes) == 1
    sentence = (
        "The demo user explicitly confirmed a groceries alert as normal. Recheck future evidence."
    )
    assert memory.writes == [{"content": sentence}]
    for forbidden in (
        tx["id"],
        tx["account_token"],
        tx["merchant_display"],
        "300",
        CUSTOMER,
        ACCOUNT,
    ):
        assert forbidden not in sentence
    assert client.post(path, json=body).json()["memory_id"] == receipt["memory_id"]
    assert len(memory.writes) == 1
    assert (
        client.post(path, json={"decision": "review", "consent_to_memory": True}).status_code == 409
    )
    assert (
        next(a for a in client.get("/api/v1/alerts").json() if a["alert_id"] == alert["alert_id"])[
            "status"
        ]
        == "normal"
    )
    related = "/api/v1/transactions/txn_fixture_2/relevant-memories"
    result = client.get(related).json()
    assert (
        result["retrieval_mode"] == "remote_verified"
        and result["memories"][0]["memory_id"] == receipt["memory_id"]
    )
    later = client.post("/api/v1/analyses", json={"transaction_id": "txn_fixture_2"}).json()
    assert later["needs_human"] and later["alert_type"] == "amount_anomaly"
    explanation = client.post("/api/v1/transactions/txn_fixture_2/explanation").json()
    assert explanation["needs_human"] and explanation["alert_type"] == "amount_anomaly"
    assert documents[-1]["features"]["prior_user_confirmation"] == "normal"
    assert set(documents[-1]) == {
        "task",
        "alert_type",
        "severity",
        "needs_human",
        "reason_codes",
        "features",
    }
    assert not any(
        value in json.dumps(documents)
        for value in (tx["id"], tx["account_token"], tx["merchant_display"], "300.0")
    )
    with TestClient(build()) as restarted:
        restarted.post("/api/v1/auth/login", json={"role": "user", "passcode": "test-login"})
        assert restarted.get("/api/v1/memories").json()[0]["memory_id"] == receipt["memory_id"]
        assert restarted.get(related).json()["memories"]
    memory.fail = "delete"
    assert client.delete("/api/v1/memories/" + receipt["memory_id"]).status_code == 502
    assert client.get(related).json()["memories"]
    memory.fail = None
    assert client.delete("/api/v1/memories/" + receipt["memory_id"]).status_code == 204
    assert client.get(related).json()["memories"] == [] and not memory.records
    deleted = client.get(
        "/api/v1/memories/" + receipt["memory_id"] + "/deletion-verification"
    ).json()
    assert deleted["status"] == "absent" and deleted["checked_at"]
    assert client.delete("/api/v1/memories/" + receipt["memory_id"]).status_code == 404
    with TestClient(build()) as restarted:
        restarted.post("/api/v1/auth/login", json={"role": "user", "passcode": "test-login"})
        assert restarted.get(related).json()["memories"] == []
        assert restarted.post(path, json=body).json()["memory_id"] == receipt["memory_id"]
    assert len(memory.writes) == 1


@pytest.mark.parametrize(
    "decision,consent,enabled,writes,status",
    [
        ("normal", True, True, 1, "written"),
        ("normal", False, True, 0, "not-requested"),
        ("review", True, True, 0, "skipped"),
        ("normal", True, False, 0, "skipped"),
    ],
)
def test_consent_matrix(lifecycle, decision, consent, enabled, writes, status):
    client, memory, _, _ = lifecycle
    client.app.state.settings.allow_memory_write = enabled
    result = client.post(
        "/api/v1/alerts/alert_txn_fixture_1/confirmations",
        json={"decision": decision, "consent_to_memory": consent},
    )
    assert result.status_code == 200 and result.json()["memory_status"] == status
    assert len(memory.writes) == writes


@pytest.mark.parametrize("failure", ["timeout", "rejected"])
def test_remote_failure_never_rolls_back_confirmation_or_retries_write(lifecycle, failure):
    client, memory, _, _ = lifecycle
    memory.fail = failure
    path = "/api/v1/alerts/alert_txn_fixture_1/confirmations"
    body = {"decision": "normal", "consent_to_memory": True}
    result = client.post(path, json=body)
    assert result.status_code == 200
    assert result.json()["memory_status"] in {"written", "pending", "failed"}
    assert client.app.state.store.status("fixture-owner", "alert_txn_fixture_1") == "normal"
    for _ in range(3):
        assert client.post(path, json=body).status_code == 200
    assert len(memory.writes) == 1
    if failure == "rejected":
        assert result.json()["memory_status"] == "failed"


def test_concurrent_confirmations_and_storage_failure(lifecycle):
    client, memory, _, _ = lifecycle
    path = "/api/v1/alerts/alert_txn_fixture_1/confirmations"
    body = {"decision": "normal", "consent_to_memory": True}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: client.post(path, json=body), range(4)))
    assert all(r.status_code == 200 for r in results)
    assert len(memory.writes) == 1
    with client.app.state.store.connect() as db:
        db.execute(
            "CREATE TRIGGER fail_confirmation BEFORE INSERT ON confirmations BEGIN SELECT RAISE(ABORT,'private failure'); END"
        )
    response = client.post("/api/v1/alerts/alert_txn_fixture_2/confirmations", json=body)
    assert response.status_code == 500 and "private failure" not in response.text
    assert len(memory.writes) == 1


def test_wrong_owner_and_invalid_requests_never_write(lifecycle):
    client, memory, _, _ = lifecycle
    path = "/api/v1/alerts/alert_txn_fixture_1/confirmations"
    assert (
        client.post(path, json={"decision": "invalid", "consent_to_memory": True}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/alerts/missing/confirmations",
            json={"decision": "normal", "consent_to_memory": True},
        ).status_code
        == 404
    )
    client.app.state.settings.demo_user_id = "different-owner"
    assert (
        client.post(path, json={"decision": "normal", "consent_to_memory": True}).status_code == 404
    )
    assert client.get("/api/v1/transactions/txn_fixture_1/relevant-memories").status_code == 404
    assert not memory.writes


def test_real_nessie_normalization_positive_alert_other_memory_and_insufficient_evidence(tmp_path):
    settings = Settings(
        _env_file=None,
        transaction_provider="nessie",
        database_path=tmp_path / "nessie.db",
        nessie_api_key="test-nessie",
        nessie_customer_id=CUSTOMER,
        backboard_api_key="isolated-fake-key",
        gemini_api_key="",
        allow_memory_write=True,
    )
    app = create_app(settings)

    def upstream(request):
        assert request.method == "GET"
        if request.url.path.endswith("/accounts"):
            rows = [
                {
                    "_id": ACCOUNT,
                    "customer_id": CUSTOMER,
                    "type": "Checking",
                    "balance": 100,
                    "rewards": 0,
                }
            ]
        elif request.url.path.endswith("/withdrawals"):
            rows = [
                {
                    "id": "e" * 24,
                    "amount": 300,
                    "transaction_date": "2026-10-17",
                    "status": "completed",
                }
            ]
        elif request.url.path.endswith("/transfers"):
            rows = [
                {
                    "id": "f" * 24,
                    "amount": 900,
                    "transaction_date": "2026-10-17",
                    "status": "completed",
                }
            ]
        else:
            rows = []
        return httpx.Response(200, json=rows)

    app.state.nessie = NessieClient("test-nessie", transport=httpx.MockTransport(upstream))
    memory = TestMemoryHTTP()
    app.state.backboard_transport = httpx.MockTransport(memory)
    with TestClient(app) as client:
        rows = client.get("/api/v1/transactions").json()
        debit = next(t for t in rows if t["kind"] == "withdrawal")
        unknown = next(t for t in rows if t["kind"] == "transfer")
        analysis = client.post("/api/v1/analyses", json={"transaction_id": debit["id"]}).json()
        assert analysis["alert_type"] == "amount_anomaly" and analysis["needs_human"]
        (alert,) = client.get("/api/v1/alerts").json()
        receipt = client.post(
            "/api/v1/alerts/" + alert["alert_id"] + "/confirmations",
            json={"decision": "normal", "consent_to_memory": True},
        ).json()
        assert receipt["memory_status"] == "written"
        assert "other alert as normal" in client.get("/api/v1/memories").json()[0]["summary"]
        assert (
            client.get("/api/v1/transactions/" + debit["id"] + "/relevant-memories").json()[
                "memories"
            ]
            == []
        )
        assert (
            client.get("/api/v1/privacy/preview/" + debit["id"]).json()["safe_payload"][
                "prior_user_confirmation"
            ]
            == "unknown"
        )
        unknown_result = client.post(
            "/api/v1/analyses", json={"transaction_id": unknown["id"]}
        ).json()
        assert (
            unknown_result["alert_type"] == "none"
            and "Insufficient evidence" in unknown_result["evidence"][0]
        )
        explanation = client.post("/api/v1/transactions/" + unknown["id"] + "/explanation").json()
        assert (
            not explanation["sent_to_provider"]
            and "Insufficient evidence" in explanation["why_flagged"]
        )
        assert "An absent alert does not prove" in explanation["what_it_means"]
        assert client.delete("/api/v1/memories/" + receipt["memory_id"]).status_code == 204
        assert (
            client.get("/api/v1/transactions/" + debit["id"] + "/relevant-memories").json()[
                "memories"
            ]
            == []
        )
        assert app.state.store.list_transactions(settings.demo_user_id) == []


def test_rule_outcome_semantics():
    tx = Transaction(
        id="txn_test",
        account_token="acct_test",
        amount=20,
        currency="USD",
        direction="debit",
        occurred_at=datetime.now(timezone.utc),
        merchant_display="TEST",
        merchant_category="other",
        source="nessie",
        is_subscription=False,
    )
    assert evaluation_outcome(tx) == "EVALUATED_NO_ALERT"
    tx.direction = "unknown"
    assert evaluation_outcome(tx) == "INSUFFICIENT_EVIDENCE"
    tx.direction = "credit"
    assert evaluation_outcome(tx) == "RULE_NOT_APPLICABLE"
    tx._settlement_status = "pending"
    assert evaluation_outcome(tx) == "RULE_NOT_APPLICABLE"


def test_remote_deleted_memory_never_reenters_context_after_local_delete_failure(lifecycle):
    client, memory, _, build = lifecycle
    receipt = client.post(
        "/api/v1/alerts/alert_txn_fixture_1/confirmations",
        json={"decision": "normal", "consent_to_memory": True},
    ).json()
    mid = receipt["memory_id"]
    with client.app.state.store.connect() as db:
        db.execute(
            "CREATE TRIGGER fail_local_delete BEFORE DELETE ON memories BEGIN SELECT RAISE(ABORT,'isolated delete failure'); END"
        )
    response = client.delete("/api/v1/memories/" + mid)
    assert response.status_code == 500 and "isolated delete failure" not in response.text
    assert not memory.records  # remote provider acknowledged deletion before the local failure
    preview = client.get("/api/v1/privacy/preview/txn_fixture_2").json()
    assert preview["safe_payload"]["prior_user_confirmation"] == "unknown"
    assert client.app.state.store.relevant_memory_rows("fixture-owner") == []
    with TestClient(build()) as restarted:
        restarted.post("/api/v1/auth/login", json={"role": "user", "passcode": "test-login"})
        assert (
            restarted.get("/api/v1/privacy/preview/txn_fixture_2").json()["safe_payload"][
                "prior_user_confirmation"
            ]
            == "unknown"
        )
    with client.app.state.store.connect() as db:
        db.execute("DROP TRIGGER fail_local_delete")
    assert client.delete("/api/v1/memories/" + mid).status_code == 204


def test_confirmed_memory_is_not_accessible_to_another_owner(lifecycle):
    client, memory, _, _ = lifecycle
    receipt = client.post(
        "/api/v1/alerts/alert_txn_fixture_1/confirmations",
        json={"decision": "normal", "consent_to_memory": True},
    ).json()
    client.app.state.settings.demo_user_id = "different-owner"
    assert client.get("/api/v1/memories").json() == []
    assert client.delete("/api/v1/memories/" + receipt["memory_id"]).status_code == 404
    assert len(memory.records) == 1
    assert (
        client.get(
            "/api/v1/memories/" + receipt["memory_id"] + "/deletion-verification"
        ).status_code
        == 404
    )
