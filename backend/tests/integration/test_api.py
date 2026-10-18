from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


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


def test_analysis_matches_preview_and_get_limit(client):
    assert client.get("/api/v1/transactions?limit=0").status_code == 422
    assert len(client.get("/api/v1/transactions?limit=2").json()) == 2
    analysis = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"}).json()
    assert analysis["alert_type"] == "duplicate" and analysis["provider_mode"] == "rules-only"
    payload = client.get("/api/v1/privacy/preview/txn_syn_004").json()["safe_payload"]
    assert payload["same_category_same_amount_24h_count"] == 2
