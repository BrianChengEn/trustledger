import json
from pathlib import Path

from app.adapters.dev_library import load_document, reset_dev_owners, seed, transactions_for
from app.adapters.synthetic import load_transactions
from app.core.rules import analyze
from app.core.store import Store
from app.schemas.api import SafePayload

ROOT = Path(__file__).resolve().parents[4]


def test_safe_payload_keeps_the_eight_approved_fields():
    assert set(SafePayload.model_fields) == {
        "merchant_category",
        "amount_bucket",
        "currency",
        "local_day_part",
        "same_category_same_amount_24h_count",
        "is_subscription",
        "subscription_delta_bucket",
        "prior_user_confirmation",
    }


def test_dev_library_matches_current_rules_and_isolates_owners():
    document = load_document()
    assert document["ground_truth_fraud_labels"] is False
    for owner, rows in document["owners"].items():
        parsed = transactions_for(owner, document)
        for row, raw in zip(parsed, rows, strict=True):
            result = analyze(row, parsed, "req_dev_library")
            assert result.alert_type == raw["expected_alert_type"]
            assert result.needs_human is (raw["expected_alert_type"] != "none")
            assert result.confidence == 1.0
        assert {row.account_token for row in parsed} == {f"acct_dev_{owner[-1]}1"}


def test_seed_is_idempotent_and_leaves_the_eight_demo_rows(tmp_path):
    store = Store(tmp_path / "dev.db")
    load_transactions(store, "demo-user-001")
    before = [row.model_dump(mode="json") for row in store.list_transactions("demo-user-001")]
    first = seed(store)
    second = seed(store)
    assert first == second
    assert first == {"dev-library-user-a": 9, "dev-library-user-b": 2}
    assert [row.model_dump(mode="json") for row in store.list_transactions("demo-user-001")] == before
    assert len(before) == 18
    assert {row.id for row in store.list_transactions("demo-user-001")} >= {
        "txn_syn_001", "txn_syn_002", "txn_syn_003", "txn_syn_004",
        "txn_syn_005", "txn_syn_006", "txn_syn_007", "txn_syn_008",
    }
    assert store.status("dev-library-user-a", "alert_txn_dev_a_duplicate") == "normal"
    assert store.status("dev-library-user-b", "alert_txn_dev_b_large") == "open"
    assert store.list_transactions("dev-library-user-b")[0].account_token == "acct_dev_b1"
    removed = reset_dev_owners(store)
    assert removed == ["dev-library-user-a", "dev-library-user-b"]
    assert store.list_transactions("dev-library-user-a") == []
    assert [row.model_dump(mode="json") for row in store.list_transactions("demo-user-001")] == before
    again = seed(store)
    assert again["dev-library-user-a"] == 9


def test_frontend_fixture_uses_canonical_transactions_and_response_models():
    from app.schemas.api import (
        Alert, Analysis, Confirmation, ErrorEnvelope, Explanation, MemorySummary, PrivacyPreview,
    )
    from app.schemas.transaction import Transaction

    payload = json.loads((ROOT / "frontend" / "src" / "fixtures" / "examples.json").read_text())
    assert payload["synthetic"] is True
    assert payload["live_provider_verified"] is False
    canonical = json.loads((ROOT / "fixtures" / "synthetic-transactions.json").read_text())
    assert payload["baseline_transactions"] == canonical
    for row in payload["baseline_transactions"]:
        Transaction.model_validate(row)
    for row in payload["dev_library_transactions"]:
        Transaction.model_validate(row)
    for name in ("rules_only", "jev_shape"):
        Analysis.model_validate(payload["analyses"][name])
    for name in ("duplicate_open", "amount_open", "subscription_open", "confirmed_normal"):
        Alert.model_validate(payload["alerts"][name])
    for name in ("template_shape", "fallback_shape", "gemini_shape"):
        explanation = Explanation.model_validate(payload["explanations"][name])
        assert set(explanation.safe_payload.model_fields_set) == set(SafePayload.model_fields)
        assert "merchant_display" not in explanation.safe_payload.model_dump()
    Confirmation.model_validate(payload["confirmation"])
    MemorySummary.model_validate(payload["memory"])
    PrivacyPreview.model_validate(payload["privacy_preview"])
    ErrorEnvelope.model_validate(payload["error"])
    assert payload["empty_transactions"] == []
    assert payload["loading"] == {"state": "loading"}
    assert payload["alerts"]["confirmed_normal"]["status"] == "normal"
    assert payload["alerts"]["amount_open"]["status"] == "open"
    assert payload["explanations"]["gemini_shape"]["why_flagged"].startswith("Synthetic shape example.")
    assert payload["explanations"]["fallback_shape"]["explanation_mode"] == "fallback"
    assert payload["analyses"]["jev_shape"]["evidence"][0].startswith("Synthetic fixture shape.")
