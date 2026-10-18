"""Build the Fraud Intelligence Lab's static data from Brian's saved BankSim benchmark artifacts.

Read-only: it never writes under evaluation/. It stops if any number it would publish disagrees with the leaderboard.

    python3 frontend/scripts/export_fraudlab_data.py

Ranking order is the benchmark protocol's (evaluation/research/benchmark/PROTOCOL.txt, section 3):
higher score first, then larger amount, then lower row index.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "evaluation/research"
BENCH = RESEARCH / "benchmark"
OUT = ROOT / "frontend/src/fraudlab/data"
BUDGET = 919


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def score_file(model: str) -> Path:
    for folder in (BENCH / "trustledger/scores", BENCH / "public/scores"):
        if (folder / f"{model}.npz").exists():
            return folder / f"{model}.npz"
    raise SystemExit(f"no saved scores for {model}")


def fraud_ranks(z) -> np.ndarray:
    order = np.lexsort((np.arange(len(z["score"])), -z["amount"], -z["score"]))
    return np.flatnonzero(z["y"][order] == 1) + 1, order


def main() -> None:
    board = json.loads((BENCH / "leaderboard.json").read_text())
    framework = json.loads((RESEARCH / "v2/results/framework_v2.json").read_text())
    uncertainty = json.loads((BENCH / "uncertainty.json").read_text())
    rows_total, fraud_total = board["test_rows"], board["test_fraud"]
    assert board["review_budget"] == BUDGET and not board["alignment_problems"]

    models, sources = [], {}
    headline_order = None
    for row in board["leaderboard"]:
        name = row["model"]
        path = score_file(name)
        z = np.load(path)
        assert len(z["y"]) == rows_total and int(z["y"].sum()) == fraud_total, name
        ranks, order = fraud_ranks(z)
        tp = int((ranks <= BUDGET).sum())
        # The published TP/FP must be reproducible from the saved scores and labels, or nothing is exported.
        assert tp == row["TP"] and BUDGET - tp == row["FP"] and fraud_total - tp == row["FN"], (name, tp, row["TP"])
        assert rows_total - fraud_total - row["FP"] == row["TN"], name
        ap_protocol = float(np.mean(np.arange(1, fraud_total + 1) / ranks))
        # scikit-learn groups tied scores; the protocol ranking breaks ties by amount, so tie-heavy models differ a little.
        # Models that output (almost) only 0/1 have no real ranking, so no curve is drawn for them.
        curve_ok = row["score_unique_values"] > 1000
        if curve_ok:
            tolerance = 2e-5 if name == "v2_merchant_step_causal" else 6e-3
            assert abs(ap_protocol - row["average_precision"]) < tolerance, (name, ap_protocol, row["average_precision"])
        models.append({
            "model": name, "track": row["track"], "fidelity": row["fidelity"], "architecture": row["architecture"],
            "leakage_status": row["leakage_status"], "source_url": row["source_url"],
            "average_precision": row["average_precision"], "roc_auc": row["roc_auc"],
            "TP": row["TP"], "FP": row["FP"], "FN": row["FN"], "TN": row["TN"],
            "precision": row["precision"], "recall": row["recall"], "alerts": row["alerts"],
            "score_unique_values": row["score_unique_values"], "curve_ok": curve_ok, "ap_protocol_order": round(ap_protocol, 6),
            "fraud_ranks": ranks.tolist(),
        })
        sources[rel(path)] = sha256(path)
        if name == "v2_merchant_step_causal":
            headline_order = (z, order)

    z, order = headline_order
    ranks = np.flatnonzero(z["y"][order] == 1) + 1
    keep = set(range(1, 1201)) | set(ranks.tolist())
    rows = []
    for rank in sorted(keep):
        i = int(order[rank - 1])
        rows.append([rank, round(float(z["score"][i]), 6), int(z["y"][i]), round(float(z["amount"][i]), 2), int(z["step"][i]),
                     int(z["customer"][i]), int(z["merchant"][i]), int(z["category"][i])])

    splits = framework["splits"]["counts"]
    assert splits["test"] == {"rows": rows_total, "fraud": fraud_total}
    keys = {
        "customer:v2_merchant_step_causal-minus-trackB_sushmitha_lgbm": "headline_vs_public_lgbm_customer_blocks",
        "step:v2_merchant_step_causal-minus-trackB_sushmitha_lgbm": "headline_vs_public_lgbm_step_blocks",
        "customer:v2_enriched_sqrt-minus-trackA_atavci_xgb_logistic": "matched_features_vs_xgb_customer_blocks",
        "step:v2_enriched_sqrt-minus-trackA_atavci_xgb_logistic": "matched_features_vs_xgb_step_blocks",
    }
    boot = {}
    for src, label in keys.items():
        b = uncertainty["bootstrap"][src]
        boot[label] = {"block_count": b["block_count"], "ap_difference": {k: b["ap"][k] for k in ("mean", "ci95_low", "ci95_high", "includes_zero")}}
    evidence = {
        "dataset": {"name": "BankSim", "rows": 594643, "fraud": 7200, "steps": [0, 179], "license": "CC BY-NC-SA 4.0"},
        "splits": {"train": [0, 119], "selection": [120, 134], "confirm": [135, 149], "test": [150, 179], "counts": splits,
                   "test_limit": framework["splits"]["test_limit"]},
        "budget": BUDGET, "test_rows": rows_total, "test_fraud": fraud_total,
        "selected_model_on_selection_slice": framework["selected_model"],
        "hgb_hyperparameters": framework["hgb_hyperparameters"], "merchant_shrinkage_alpha": framework["merchant_shrinkage_alpha"],
        "validation_ranking": [{"name": v["name"], "val_ap": v["val_ap"], "family": v["family"], "merchant": v["merchant"]}
                               for v in framework["validation_ranking"]],
        "bootstrap": boot,
        "merchant_concentration": {k: v for k, v in uncertainty["merchant_tp"].items()},
    }
    commit = subprocess.run(["git", "log", "-1", "--format=%H", "--", "evaluation/research/benchmark/leaderboard.json"],
                            cwd=ROOT, capture_output=True, text=True).stdout.strip()
    for p in (BENCH / "leaderboard.json", BENCH / "uncertainty.json", RESEARCH / "v2/results/framework_v2.json",
              BENCH / "FINDINGS.txt", BENCH / "PROTOCOL.txt", BENCH / "trustledger/NOTES.txt", BENCH / "audit/AUDIT.txt"):
        sources[rel(p)] = sha256(p)
    provenance = {"generated_by": "frontend/scripts/export_fraudlab_data.py", "leaderboard_last_changed_in_commit": commit,
                  "row_order": "score descending, then amount descending, then row index ascending (PROTOCOL.txt section 3)",
                  "sources_sha256": dict(sorted(sources.items()))}
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("models", models), ("rows", rows), ("evidence", evidence), ("provenance", provenance)):
        (OUT / f"{name}.json").write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    print(f"exported {len(models)} models, {len(rows)} ranked rows; every TP/FP/FN/TN reproduced from saved scores")


if __name__ == "__main__":
    sys.exit(main())
