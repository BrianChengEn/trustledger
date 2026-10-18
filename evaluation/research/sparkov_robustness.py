"""Second-dataset check: amount and category only.

The local Sparkov export has corrupted card numbers, so customer history is not used.
Rows are ordered by unix_time. Fit on the earliest 70 percent, select on the next 15,
and report the final 15 once. No names, streets, or card numbers are written.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve
from sklearn.preprocessing import StandardScaler

SOURCE = Path("/tmp/tl-eval-data/fraudTrain.csv")
OUT = Path(__file__).resolve().parent / "results" / "sparkov_robustness.json"
SEED = 20261017


def load():
    unix, amount, category, y = [], [], [], []
    with SOURCE.open(newline="") as handle:
        reader = csv.reader(handle)
        next(reader)
        for row in reader:
            unix.append(int(float(row[19])))
            amount.append(float(row[5]))
            category.append(row[4])
            y.append(int(float(row[22])))
    order = np.argsort(np.asarray(unix), kind="mergesort")
    codes = {}
    cat = np.empty(len(order), dtype=np.int16)
    for index, name in enumerate(category):
        codes.setdefault(name, len(codes))
        cat[index] = codes[name]
    return {
        "unix": np.asarray(unix, dtype=np.int64)[order],
        "amount": np.asarray(amount, dtype=np.float64)[order],
        "y": np.asarray(y, dtype=np.int8)[order],
        "cat": cat[order],
        "names": {code: name for name, code in codes.items()},
    }


def confusion(y, pred):
    pred = pred.astype(bool)
    truth = y.astype(bool)
    tp = int(np.sum(pred & truth))
    fp = int(np.sum(pred & ~truth))
    tn = int(np.sum(~pred & ~truth))
    fn = int(np.sum(~pred & truth))
    precision = None if tp + fp == 0 else tp / (tp + fp)
    recall = None if tp + fn == 0 else tp / (tp + fn)
    f1 = None if not precision or not recall else 2 * precision * recall / (precision + recall)
    fpr = None if fp + tn == 0 else fp / (fp + tn)
    return {
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        "precision": precision, "recall": recall, "f1": f1, "fpr": fpr,
        "alerts": tp + fp,
    }


def best_f1(y, score):
    precision, recall, thresholds = precision_recall_curve(y, score)
    if len(thresholds) == 0:
        return float(np.max(score))
    total = precision[:-1] + recall[:-1]
    f1 = np.zeros_like(thresholds)
    ok = total > 0
    f1[ok] = 2 * precision[:-1][ok] * recall[:-1][ok] / total[ok]
    return float(thresholds[int(np.argmax(f1))])


def topk(score, amount, k):
    order = np.lexsort((np.arange(len(score)), -amount, -score))
    pred = np.zeros(len(score), dtype=bool)
    pred[order[:k]] = True
    return pred


def one_hot(codes, width):
    out = np.zeros((len(codes), width), dtype=np.float64)
    valid = codes < width
    out[np.arange(len(codes))[valid], codes[valid]] = 1.0
    return out


def main():
    data = load()
    n = len(data["y"])
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)
    train, val, test = np.arange(n) < train_end, (np.arange(n) >= train_end) & (np.arange(n) < val_end), np.arange(n) >= val_end
    y, amount, cat = data["y"], data["amount"], data["cat"]
    width = int(cat[train].max()) + 1
    x = np.column_stack([np.log1p(amount), one_hot(cat, width)])
    scaler = StandardScaler()
    lr = LogisticRegression(max_iter=300, class_weight="balanced", random_state=SEED)
    lr.fit(scaler.fit_transform(x[train]), y[train])
    lr_val = lr.predict_proba(scaler.transform(x[val]))[:, 1]
    lr_test = lr.predict_proba(scaler.transform(x[test]))[:, 1]
    pos = max(1, int(y[train].sum()))
    weight = np.where(y[train] == 1, 0.5 * train_end / pos, 0.5 * train_end / max(1, train_end - pos))
    hgb = HistGradientBoostingClassifier(
        max_iter=80, learning_rate=0.08, max_leaf_nodes=31, min_samples_leaf=40,
        l2_regularization=0.1, random_state=SEED,
    )
    hgb.fit(x[train], y[train], sample_weight=weight)
    hgb_val = hgb.predict_proba(x[val])[:, 1]
    hgb_test = hgb.predict_proba(x[test])[:, 1]
    rates = np.array([
        float(y[train & (cat == code)].mean()) if np.any(train & (cat == code)) else 0.0
        for code in range(width)
    ])
    scores = {
        "amount_score": (amount[val], amount[test]),
        "threshold_250": ((amount[val] >= 250).astype(float), (amount[test] >= 250).astype(float)),
        "amount_category_lr": (lr_val, lr_test),
        "amount_category_hgb": (hgb_val, hgb_test),
        "category_base_rate": (rates[cat[val]], rates[cat[test]]),
    }
    prod_k = int(np.sum(amount[test] >= 250))
    models = {}
    val_ap = {}
    for name, (val_score, test_score) in scores.items():
        threshold = best_f1(y[val], val_score)
        val_ap[name] = float(average_precision_score(y[val], val_score))
        models[name] = {
            "validation_average_precision": val_ap[name],
            "test_average_precision": float(average_precision_score(y[test], test_score)),
            "test_f1_threshold": confusion(y[test], test_score >= threshold),
            "test_matched_250_alert_count": confusion(y[test], topk(test_score, amount[test], prod_k)),
            "threshold": threshold,
        }
    pool = ["amount_score", "threshold_250", "amount_category_lr", "amount_category_hgb"]
    winner = max(pool, key=lambda name: val_ap[name])
    payload = {
        "dataset": "Sparkov fraudTrain export, truncated Excel file, customer id unusable",
        "rows": n,
        "fraud": int(y.sum()),
        "splits": {
            "train_rows": int(train.sum()),
            "validation_rows": int(val.sum()),
            "test_rows": int(test.sum()),
            "train_fraud": int(y[train].sum()),
            "validation_fraud": int(y[val].sum()),
            "test_fraud": int(y[test].sum()),
            "test_unix_start": int(data["unix"][test][0]),
            "test_unix_end": int(data["unix"][test][-1]),
        },
        "features": "log amount and category only; no customer, merchant, name, or card number",
        "selected_by_validation_average_precision": winner,
        "validation_average_precision": {name: val_ap[name] for name in scores},
        "models": models,
        "caveat": "This file is not the official Kaggle Sparkov release. It checks whether the BankSim ranking result depends on one simulator.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({
        "winner": winner,
        "test_fraud": payload["splits"]["test_fraud"],
        "test_rows": payload["splits"]["test_rows"],
        "ap": {name: round(models[name]["test_average_precision"], 4) for name in scores},
        "f1": {name: models[name]["test_f1_threshold"] for name in pool},
    }, indent=2))


if __name__ == "__main__":
    main()
