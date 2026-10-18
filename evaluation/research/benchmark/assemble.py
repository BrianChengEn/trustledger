"""Combine saved BankSim score files into one leaderboard.

Rank by test average precision. The 919-alert counts are the operating point.
This script recomputes metrics from scores. It does not train models.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from contract import (
    ALERT_BUDGET,
    TEST_FRAUD,
    TEST_ROWS,
    evaluate,
    fingerprint,
)


def load_scores(roots):
    files = []
    for root in roots:
        files.extend(sorted(Path(root).rglob("*.npz")))
    models = []
    for path in files:
        if path.name.startswith("."):
            continue
        with np.load(path) as payload:
            row = {key: np.array(payload[key]) for key in payload.files}
        sidecar = path.with_suffix(".json")
        meta = json.loads(sidecar.read_text()) if sidecar.exists() else {}
        row["path"] = str(path)
        row["meta"] = meta
        row["name"] = meta.get("model") or path.stem
        models.append(row)
    return models


def check_alignment(models):
    if not models:
        raise SystemExit("No score files found")
    reference = models[0]
    problems = []
    if len(reference["y"]) != TEST_ROWS or int(reference["y"].sum()) != TEST_FRAUD:
        problems.append(
            f"{reference['name']} population {len(reference['y'])}/{int(reference['y'].sum())}"
        )
    keys = ("y", "amount", "step", "customer", "merchant", "category")
    base = {key: fingerprint(reference[key]) for key in keys}
    for model in models[1:]:
        for key in keys:
            if fingerprint(model[key]) != base[key]:
                problems.append(f"{model['name']} {key} fingerprint differs")
        if len(model["score"]) != len(reference["y"]):
            problems.append(f"{model['name']} score length differs")
    return problems


def row_for(model):
    metrics = evaluate(model["y"], model["score"], model["amount"], ALERT_BUDGET)
    meta = model["meta"]
    return {
        "model": model["name"],
        "track": meta.get("track"),
        "fidelity": meta.get("fidelity"),
        "source_url": meta.get("source_url"),
        "architecture": meta.get("architecture"),
        "leakage_status": meta.get("leakage_status"),
        "train_seconds": meta.get("train_seconds"),
        "predict_seconds": meta.get("predict_seconds"),
        "feature_seconds": meta.get("feature_seconds"),
        "average_precision": metrics["average_precision"],
        "roc_auc": metrics["roc_auc"],
        "TP": metrics["TP"],
        "FP": metrics["FP"],
        "TN": metrics["TN"],
        "FN": metrics["FN"],
        "precision": metrics["precision"],
        "recall": metrics["recall"],
        "f1": metrics["f1"],
        "accuracy": metrics["accuracy"],
        "balanced_accuracy": metrics["balanced_accuracy"],
        "fpr": metrics["fpr"],
        "alerts": metrics["alerts"],
        "score_unique_values": metrics["score_unique_values"],
        "path": model["path"],
    }


def main(argv):
    roots = argv[1:] or [
        "evaluation/research/benchmark/public/scores",
        "evaluation/research/benchmark/trustledger/scores",
    ]
    models = load_scores(roots)
    problems = check_alignment(models)
    ranked = sorted((row_for(model) for model in models), key=lambda row: (-row["average_precision"], row["model"]))
    report = {
        "rank_key": "test_average_precision",
        "review_budget": ALERT_BUDGET,
        "test_rows": TEST_ROWS,
        "test_fraud": TEST_FRAUD,
        "alignment_problems": problems,
        "leaderboard": ranked,
    }
    out = Path("evaluation/research/benchmark/leaderboard.json")
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"models {len(ranked)} alignment_problems {len(problems)}")
    for index, row in enumerate(ranked, start=1):
        print(
            f"{index:2d} {row['model']} AP {row['average_precision']:.6f} "
            f"TP {row['TP']} FP {row['FP']} F1 {row['f1']:.4f} track {row['track']}"
        )
    if problems:
        print("ALIGNMENT")
        for problem in problems:
            print(problem)
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main(sys.argv))
