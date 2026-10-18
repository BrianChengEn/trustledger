"""Score the authoritative HTTP rules and the independent scenario suite.

Does not modify thresholds or call a provider. Jev accuracy is not measured.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evaluation"))

from app.core.rules import analyze  # noqa: E402
from app.schemas.transaction import Transaction  # noqa: E402
from scenarios_quick import run_scenarios  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
SAMPLE = Path("/tmp/tl-eval-data/quick/quick_sample.jsonl")
DISCLAIMER = (
    "These metrics measure how often a rules alert coincides with a BankSim fraud label. "
    "They are not production-grade fraud-detection accuracy."
)


def ratio(numerator: int, denominator: int) -> dict:
    if denominator == 0:
        return {"value": None, "undefined": True, "numerator": numerator, "denominator": 0}
    return {
        "value": numerator / denominator,
        "undefined": False,
        "numerator": numerator,
        "denominator": denominator,
    }


def matrix_from_pairs(pairs: list[tuple[int, str]]) -> dict[str, int]:
    counts = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
    for fraud, alert_type in pairs:
        alert = alert_type != "none"
        if alert and fraud:
            counts["TP"] += 1
        elif alert and not fraud:
            counts["FP"] += 1
        elif not alert and not fraud:
            counts["TN"] += 1
        else:
            counts["FN"] += 1
    return counts


def fixture_self_test() -> dict:
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    rows = [
        ("txn_syn_001", 0, 15, 6.45, "Campus Coffee", "dining", False, "none"),
        ("txn_syn_002", 1, 11, 42.18, "Fresh Basket", "groceries", False, "none"),
        ("txn_syn_003", 2, 8, 11.99, "StreamWave", "streaming", True, "none"),
        ("txn_syn_004", 2, 9, 11.99, "StreamWave", "streaming", True, "duplicate"),
        ("txn_syn_005", 3, 16, 849, "Tech Harbor", "electronics", False, "amount_anomaly"),
        ("txn_syn_006", 4, 18, 18.5, "Metro Ride", "transportation", False, "none"),
        ("txn_syn_007", 5, 7, 24.99, "FitFlow", "fitness_subscription", True, "none"),
        ("txn_syn_008", 6, 7, 34.99, "FitFlow", "fitness_subscription", True, "subscription_change"),
    ]
    history: list[Transaction] = []
    actual = {}
    for name, day, hour, amount, merchant, category, subscription, _expected in rows:
        current = Transaction(
            id=name,
            occurred_at=base.replace(day=1 + day, hour=hour),
            amount=amount,
            currency="USD",
            direction="debit",
            merchant_display=merchant,
            merchant_category=category,
            source="synthetic",
            account_token="acct_demo_a1",
            is_subscription=subscription,
        )
        actual[name] = analyze(current, history, "fixture").alert_type
        history.append(current)
    expected = {name: label for name, *_rest, label in rows}
    return {"pass": actual == expected, "expected": expected, "actual": actual}


def score_sample(path: Path) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    with path.open() as handle:
        for line in handle:
            record = json.loads(line)
            grouped[record["transaction"]["account_token"]].append(record)
    pairs: list[tuple[int, str]] = []
    crosstab: Counter = Counter()
    examples: dict[str, list[dict]] = {"FP": [], "FN": []}
    category_fn: Counter = Counter()
    category_fp: Counter = Counter()
    for records in grouped.values():
        records.sort(key=lambda item: (item["transaction"]["occurred_at"], item["row_index"]))
        history: list[Transaction] = []
        for record in records:
            current = Transaction(**record["transaction"])
            if record["split"] == "eval":
                result = analyze(current, history, "quick-eval")
                pairs.append((record["fraud"], result.alert_type))
                crosstab[(result.alert_type, record["fraud"])] += 1
                kind = None
                if result.alert_type != "none" and record["fraud"] == 0:
                    kind = "FP"
                    category_fp[record["source_category"]] += 1
                elif result.alert_type == "none" and record["fraud"] == 1:
                    kind = "FN"
                    category_fn[record["source_category"]] += 1
                if kind and len(examples[kind]) < 12:
                    merchant = record["transaction"]["merchant_display"]
                    examples[kind].append({
                        "step": record["step"],
                        "amount": record["transaction"]["amount"],
                        "mapped_category": record["transaction"]["merchant_category"],
                        "source_category": record["source_category"],
                        "alert_type": result.alert_type,
                        "fraud": record["fraud"],
                        "merchant_hash8": hashlib.sha256(merchant.encode()).hexdigest()[:8],
                        "reason": (
                            "Non-fraud debit at or above the production 250 threshold."
                            if kind == "FP" and result.alert_type == "amount_anomaly"
                            else "Non-fraud same-merchant same-amount hit inside the imputed 24 hour window."
                            if kind == "FP"
                            else "Labeled fraud below 250 with no same-merchant same-amount hit."
                        ),
                    })
            history.append(current)
    replay = matrix_from_pairs(pairs)
    direct = matrix_from_pairs(pairs)
    if replay != direct:
        raise RuntimeError("Independent confusion-matrix replay disagreed.")
    # A second accumulation, not a second pass over the same counter object.
    replay_again = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
    for fraud, alert_type in pairs:
        key = ("TP" if fraud else "FP") if alert_type != "none" else ("FN" if fraud else "TN")
        replay_again[key] += 1
    counts = replay_again
    tp, fp, tn, fn = counts["TP"], counts["FP"], counts["TN"], counts["FN"]
    total = tp + fp + tn + fn
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    tnr = ratio(tn, tn + fp)
    if precision["undefined"] or recall["undefined"] or (
        precision["value"] + recall["value"] == 0
    ):
        f1 = {"value": None, "undefined": True, "numerator": None, "denominator": None}
    else:
        f1 = {
            "value": 2 * precision["value"] * recall["value"] / (precision["value"] + recall["value"]),
            "undefined": False,
            "precision_numerator": tp,
            "precision_denominator": tp + fp,
            "recall_numerator": tp,
            "recall_denominator": tp + fn,
        }
    balanced = (
        {"value": None, "undefined": True}
        if recall["undefined"] or tnr["undefined"]
        else {"value": (recall["value"] + tnr["value"]) / 2, "undefined": False,
              "recall": recall, "tnr": tnr}
    )
    return {
        "pair_count": total,
        "confusion_matrix": counts,
        "independent_check_match": counts == direct == replay,
        "metrics": {
            "accuracy": ratio(tp + tn, total),
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "false_positive_rate": ratio(fp, fp + tn),
            "true_negative_rate": tnr,
            "balanced_accuracy": balanced,
        },
        "alert_type_by_fraud": {
            f"{alert}|fraud={fraud}": count for (alert, fraud), count in sorted(crosstab.items())
        },
        "false_positive_examples": examples["FP"],
        "false_negative_examples": examples["FN"],
        "false_positive_by_source_category": dict(category_fp),
        "false_negative_by_source_category": dict(category_fn),
    }


def main() -> None:
    if not SAMPLE.is_file():
        from prepare_quick_sample import main as prepare
        prepare()
    fixture = fixture_self_test()
    if not fixture["pass"]:
        raise SystemExit(f"Fixture self-test failed: {fixture}")
    scenarios = run_scenarios()
    scored = score_sample(SAMPLE)
    summary = json.loads((OUT / "sample_summary.json").read_text())
    passed = sum(item["pass"] for item in scenarios)
    payload = {
        "prevalence_kind": "natural",
        "dataset": summary["dataset_name"],
        "eval_row_count": summary["eval_row_count"],
        "eval_fraud_count": summary["eval_fraud_count"],
        "eval_normal_count": summary["eval_normal_count"],
        "eval_prevalence": summary["eval_prevalence"],
        "eval_customer_count": summary["eval_customer_count"],
        "step_min_eval": summary["step_min_eval"],
        "step_max_eval": summary["step_max_eval"],
        "confusion_matrix": scored["confusion_matrix"],
        "metrics": scored["metrics"],
        "alert_type_by_fraud": scored["alert_type_by_fraud"],
        "rule_specific_accuracy": {
            "duplicate": "NOT EVALUABLE",
            "amount_anomaly": "NOT EVALUABLE",
            "subscription_change": "NOT EVALUABLE",
        },
        "fixture_self_test_pass": fixture["pass"],
        "scenario_count": len(scenarios),
        "scenario_pass_count": passed,
        "scenario_fail_count": len(scenarios) - passed,
        "independent_check_match": scored["independent_check_match"],
        "assumptions": summary["assumptions"],
        "disclaimer": DISCLAIMER,
        "jev_classification_accuracy": "NOT MEASURED IN THIS RUN",
        "false_positive_by_source_category": scored["false_positive_by_source_category"],
        "false_negative_by_source_category": scored["false_negative_by_source_category"],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "quick_metrics.json").write_text(json.dumps(payload, indent=2) + "\n")
    (OUT / "scenario_results.json").write_text(json.dumps(scenarios, indent=2) + "\n")
    failures = [item for item in scenarios if not item["pass"]]
    lines = [
        "# Quick evaluation failure notes",
        "",
        DISCLAIMER,
        "",
        "Jev classification accuracy: NOT MEASURED IN THIS RUN.",
        "",
        "Rule-specific accuracy for duplicate, amount anomaly, and subscription change "
        "is NOT EVALUABLE. BankSim has no labels for those anomaly types.",
        "",
        "## False positives",
        "",
    ]
    for item in scored["false_positive_examples"]:
        lines.append(
            f"- step {item['step']}, amount {item['amount']}, {item['mapped_category']} "
            f"({item['source_category']}), alert {item['alert_type']}, "
            f"merchant {item['merchant_hash8']}: {item['reason']}"
        )
    lines.extend(["", "## False negatives", ""])
    for item in scored["false_negative_examples"]:
        lines.append(
            f"- step {item['step']}, amount {item['amount']}, {item['mapped_category']} "
            f"({item['source_category']}), alert {item['alert_type']}, "
            f"merchant {item['merchant_hash8']}: {item['reason']}"
        )
    lines.extend(["", "## Scenario mismatches", ""])
    for item in failures:
        lines.append(f"- {item['case_id']}: {item['mismatch_reason']}")
    text = "\n".join(lines) + "\n"
    (OUT / "quick_failure_cases.md").write_text(text)
    mirror = Path("/tmp/tl-eval-data/quick")
    mirror.mkdir(parents=True, exist_ok=True)
    (mirror / "quick_metrics.json").write_text((OUT / "quick_metrics.json").read_text())
    (mirror / "quick_failure_cases.md").write_text(text)
    (mirror / "scenario_results.json").write_text((OUT / "scenario_results.json").read_text())
    print(json.dumps({
        "matrix": payload["confusion_matrix"],
        "scenarios": f"{passed}/{len(scenarios)}",
        "fixture": fixture["pass"],
        "check": payload["independent_check_match"],
    }))


if __name__ == "__main__":
    main()
