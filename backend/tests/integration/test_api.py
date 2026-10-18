import json
from pathlib import Path

import yaml
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator


@pytest.mark.parametrize("consent", [1, "true", "false"])
def test_memory_requires_literal_boolean_consent(client, consent):
    response = client.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                           json={"decision": "normal", "consent_to_memory": consent})
    assert response.status_code == 422
    assert client.get("/api/v1/memories").json() == []


def test_memory_writes_are_disabled_by_default(monkeypatch):
    from app.core.config import Settings

    monkeypatch.delenv("ALLOW_MEMORY_WRITE", raising=False)
    assert Settings(_env_file=None).allow_memory_write is False


def test_failed_memory_does_not_undo_confirmation_or_retry_it(client):
    with client.app.state.store.connect() as db:
        db.execute("CREATE TRIGGER fail_memory BEFORE INSERT ON memories "
                   "BEGIN SELECT RAISE(FAIL, 'synthetic storage failure'); END")
    path = "/api/v1/alerts/alert_txn_syn_004/confirmations"
    body = {"decision": "normal", "consent_to_memory": True}
    response = client.post(path, json=body)
    assert response.status_code == 200
    assert response.json()["decision"] == "normal"
    assert response.json()["memory_status"] == "failed"
    assert response.json()["memory_id"] is None
    assert client.app.state.store.status("demo-user-001", "alert_txn_syn_004") == "normal"
    assert client.get("/api/v1/memories").json() == []
    assert client.post(path, json=body).json()["memory_status"] == "failed"


def test_transactions_use_persistent_sqlite_instead_of_json(client):
    store = client.app.state.store
    owner = client.app.state.settings.demo_user_id
    with store.connect() as db:
        db.execute("UPDATE demo_transactions SET amount_cents=1234 WHERE owner=? AND id=?",
                   (owner, "txn_syn_005"))
    rows = client.get("/api/v1/transactions").json()
    assert next(row for row in rows if row["id"] == "txn_syn_005")["amount"] == 12.34
    analysis = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_005"}).json()
    assert analysis["alert_type"] == "none"
    preview = client.get("/api/v1/privacy/preview/txn_syn_005").json()
    assert preview["safe_payload"]["amount_bucket"] == "10-25"

    from app.main import create_app

    with TestClient(create_app(client.app.state.settings)) as restarted:
        rows = restarted.get("/api/v1/transactions").json()
        assert len(rows) == 8
        assert next(row for row in rows if row["id"] == "txn_syn_005")["amount"] == 12.34


def test_contract_smoke(client):
    root = Path(__file__).resolve().parents[3]
    contract = yaml.safe_load((root / "contracts/internal-api.openapi.yaml").read_text())
    components = contract["components"]
    for path, schema_name in [
        ("/health", "HealthResponse"), ("/privacy/preview/txn_syn_004", "PrivacyPreview"),
    ]:
        r = client.get("/api/v1" + path)
        assert r.status_code == 200
        schema = {"$ref": f"#/components/schemas/{schema_name}", "components": components}
        Draft202012Validator(schema).validate(r.json())
    assert len(client.get("/api/v1/transactions").json()) == 8
    assert len(client.get("/api/v1/alerts").json()) == 3


def test_confirmation_memory_delete_idempotency(client):
    path = "/api/v1/alerts/alert_txn_syn_004/confirmations"
    body = {"decision": "normal", "consent_to_memory": True}
    first = client.post(path, json=body)
    assert first.status_code == 200
    assert first.json()["memory_status"] == "written"
    second = client.post(path, json=body)
    assert second.json()["memory_id"] == first.json()["memory_id"]
    assert client.post(path, json={"decision": "review", "consent_to_memory": False}).status_code == 409
    memories = client.get("/api/v1/memories").json()
    assert len(memories) == 1 and memories[0]["source"] == "local-fallback"
    assert "StreamWave" not in memories[0]["summary"]
    mid = first.json()["memory_id"]
    assert client.delete(f"/api/v1/memories/{mid}").status_code == 204
    assert client.get("/api/v1/memories").json() == []
    assert client.delete(f"/api/v1/memories/{mid}").status_code == 404


def test_consent_off_and_unknown_owner_input(client):
    r = client.post("/api/v1/alerts/alert_txn_syn_005/confirmations",
                    json={"decision": "normal", "consent_to_memory": False})
    assert r.json()["memory_status"] == "not-requested"
    assert client.get("/api/v1/memories").json() == []
    r = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004", "user_id": "another"})
    assert r.status_code == 422
    assert "another" not in r.text
    assert client.get("/api/v1/privacy/preview/missing").status_code == 404


def test_store_owner_isolation(client):
    store = client.app.state.store
    store.confirm("other-user", "alert", "normal", True, "Other user fact", "rid")
    assert client.get("/api/v1/memories").json() == []
    foreign_id = store.list_memories("other-user")[0].memory_id
    assert client.delete("/api/v1/memories/" + foreign_id).status_code == 404


def test_origin_size_and_safe_errors(client):
    assert client.post("/api/v1/analyses", headers={"origin": "https://unexpected.example"},
                       json={"transaction_id": "txn_syn_004"}).status_code == 403
    assert client.post("/api/v1/analyses", content="x" * 17000).status_code == 413
    response = client.post("/api/v1/analyses", json={"transaction_id": {"private": "secret"}})
    assert response.status_code == 422
    assert "secret" not in response.text
    assert set(response.json()["error"]) == {"code", "message", "request_id"}


def test_consented_memory_is_used_on_the_next_analysis(client):
    declined = client.post("/api/v1/alerts/alert_txn_syn_005/confirmations",
                           json={"decision": "normal", "consent_to_memory": False})
    assert declined.json()["memory_status"] == "not-requested"
    review = client.post("/api/v1/alerts/alert_txn_syn_008/confirmations",
                         json={"decision": "review", "consent_to_memory": True})
    assert review.json()["memory_status"] == "skipped"
    assert client.get("/api/v1/privacy/preview/txn_syn_005").json()["safe_payload"][
        "prior_user_confirmation"] == "unknown"
    assert client.get("/api/v1/privacy/preview/txn_syn_008").json()["safe_payload"][
        "prior_user_confirmation"] == "unknown"

    saved = client.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                        json={"decision": "normal", "consent_to_memory": True})
    assert saved.status_code == 200 and saved.json()["memory_status"] == "written"
    preview = client.get("/api/v1/privacy/preview/txn_syn_003").json()
    assert preview["safe_payload"]["prior_user_confirmation"] == "normal"
    assert "StreamWave" not in json.dumps(preview["safe_payload"])
    same = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
    assert same["alert_type"] == "duplicate" and same["needs_human"] is True
    assert any("category as normal" in line for line in same["evidence"])
    unrelated = client.get("/api/v1/privacy/preview/txn_syn_005").json()["safe_payload"]
    assert unrelated["prior_user_confirmation"] == "unknown"
    assert client.delete(f"/api/v1/memories/{saved.json()['memory_id']}").status_code == 204
    cleared = client.get("/api/v1/privacy/preview/txn_syn_004").json()["safe_payload"]
    assert cleared["prior_user_confirmation"] == "unknown"


def test_backboard_failure_and_success_keep_the_rule_contract(monkeypatch, tmp_path):
    from app.core.config import Settings
    from app.main import create_app
    from app.services.ai.jev_client import JevCallError, JevClassification

    settings = Settings(_env_file=None, database_path=tmp_path / "live.db",
                        allow_memory_write=True, backboard_api_key="synthetic-test-key")

    async def failed(*_args, **_kwargs):
        raise JevCallError("request_failed")

    monkeypatch.setattr("app.services.ai.decision.classify", failed)
    with TestClient(create_app(settings)) as live:
        body = live.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
        assert body["alert_type"] == "duplicate"
        assert body["provider_mode"] == "degraded"
        assert body["model_version"] is None
        assert live.get("/api/v1/health").json()["analysis_mode"] == "degraded"
        assert live.get("/api/v1/health").json()["status"] == "degraded"
        assert "StreamWave" not in json.dumps(body["safe_payload"] if "safe_payload" in body else body)

    async def succeeded(payload, api_key, client=None):
        assert api_key == "synthetic-test-key"
        assert "merchant_display" not in payload.model_dump()
        return JevClassification(pattern="duplicate", needs_review=0.93,
                                 choice_confidence=0.81, model_version="jev-1.13.0")

    monkeypatch.setattr("app.services.ai.decision.classify", succeeded)
    with TestClient(create_app(settings)) as live:
        body = live.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
        assert body["provider_mode"] == "rules+jev-live"
        assert body["model_version"] == "jev-1.13.0"
        assert body["alert_type"] == "duplicate" and body["needs_human"] is True
        alerts = live.get("/api/v1/alerts").json()
        assert len(alerts) == 3
        assert {item["provider_mode"] for item in alerts} == {"rules+jev-live"}
        assert live.get("/api/v1/health").json()["analysis_mode"] == "rules+jev-live"


def test_analysis_matches_preview_and_get_limit(client):
    assert client.get("/api/v1/transactions?limit=0").status_code == 422
    assert len(client.get("/api/v1/transactions?limit=2").json()) == 2
    analysis = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
    assert analysis["alert_type"] == "duplicate" and analysis["provider_mode"] == "rules-only"
    payload = client.get("/api/v1/privacy/preview/txn_syn_004").json()["safe_payload"]
    assert payload["same_category_same_amount_24h_count"] == 2
