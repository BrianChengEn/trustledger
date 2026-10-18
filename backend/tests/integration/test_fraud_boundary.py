"""Compose existing rules/privacy and F4 directly; route orchestration stays in F5."""
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from app.adapters.synthetic import load_transactions
from app.core.fraud import MockJevProvider, MockScenario, evaluate_fraud
from app.core.features import privacy_preview
from app.core.rules import analyze


@pytest.mark.parametrize("scenario", list(MockScenario))
@pytest.mark.parametrize("index", [0, 3, 4, 7])
def test_rules_privacy_provider_contract_integration(index, scenario):
    rows = load_transactions()
    tx = rows[index]
    baseline = analyze(tx, rows, "request-synthetic")
    preview = privacy_preview(tx, rows)
    result = evaluate_fraud(baseline, preview.safe_payload, MockJevProvider(scenario))
    expected = baseline.model_dump()
    if scenario != MockScenario.VALID:
        expected["provider_mode"] = "degraded"
    assert result.analysis.model_dump() == expected
    contract = yaml.safe_load((Path(__file__).resolve().parents[3]
                               / "contracts/internal-api.openapi.yaml").read_text())
    Draft202012Validator({"$ref": "#/components/schemas/Analysis",
                          "components": contract["components"]}).validate(
                              result.analysis.model_dump(mode="json"))


def test_raw_sentinels_do_not_cross_boundary_or_escape_failures(caplog):
    rows = load_transactions()
    tx = rows[4].model_copy(update={
        "merchant_display": "PRIVATE PERSON key=synthetic-secret",
        "merchant_category": "raw-private-category",
        "account_token": "acct_private_sentinel",
        "id": "txn_private_sentinel",
    })
    baseline = analyze(tx, rows, "private-request-sentinel")
    preview = privacy_preview(tx, rows)
    seen = []

    class Spy:
        def assess(self, features):
            seen.append(features.model_dump_json())
            raise RuntimeError("raw-provider-body key=synthetic-secret")

    result = evaluate_fraud(baseline, preview.safe_payload, Spy())
    assert seen and result.analysis.provider_mode == "degraded"
    for value in [tx.merchant_display, tx.merchant_category, tx.account_token, tx.id,
                  "private-request-sentinel", "849", "2026-"]:
        assert value not in seen[0]
    assert result.analysis.transaction_id == tx.id  # Identity stays local, as the API requires.
    assert "synthetic-secret" not in result.analysis.model_dump_json() + caplog.text
    assert result.analysis.confidence == baseline.confidence == 1.0


def test_existing_http_analysis_remains_rules_only(client):
    rows = load_transactions()
    for index in [0, 3, 4, 7]:
        response = client.post("/api/v1/analyses", json={"transaction_id": rows[index].id})
        assert response.status_code == 200
        expected = analyze(rows[index], rows, response.headers["x-request-id"])
        assert response.json() == expected.model_dump(mode="json")
    assert client.get("/api/v1/health").json()["analysis_mode"] == "rules-only"
