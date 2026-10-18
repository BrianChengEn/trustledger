"""Chronological architecture comparison on BankSim.

Selection is precommitted before looking at test labels:
- fit on steps 0-119
- choose thresholds and the winning model on steps 120-149
- report steps 150-179 once
- if two product-feasible models are within 0.01 validation average precision,
  keep the simpler one
- category base-rate and native-category models are diagnostics, not product candidates

No production code is imported in a way that changes it. Jev and Gemini are not called.
"""

from __future__ import annotations

import csv
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve
from sklearn.preprocessing import StandardScaler

SEED = 20261017
TRAIN_MAX = 119
VAL_MAX = 149
SOURCE = Path("/tmp/tl-eval-data/banks.csv")
OUT = Path(__file__).resolve().parent / "results" / "architecture_benchmark.json"
MAPPED = {
    "es_barsandrestaurants": "dining",
    "es_food": "groceries",
    "es_hyper": "groceries",
    "es_transportation": "transportation",
    "es_tech": "electronics",
}
PRODUCT_MODELS = [
    "prod_rules",
    "doc_rules_mapped",
    "amount_score",
    "customer_z",
    "safe_payload_lr",
    "explainable_lr",
    "history_hgb",
    "mapped_lr",
    "mapped_hgb",
]
SIMPLICITY = {name: index for index, name in enumerate(PRODUCT_MODELS)}


def load_rows(path: Path):
    rows = []
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = [cell.strip() for cell in next(reader)]
        if header[:10] != [
            "step", "customer", "age", "gender", "zipcodeOri", "merchant",
            "zipMerchant", "category", "amount", "fraud",
        ]:
            raise SystemExit(f"Unexpected BankSim header: {header}")
        for index, row in enumerate(reader):
            row = [cell.strip().strip("'") for cell in row]
            label = row[9]
            if label not in {"0", "1"}:
                raise SystemExit("Fraud label was not 0 or 1")
            rows.append((int(row[0]), index, row[1], row[5], row[7], float(row[8]), int(label)))
    rows.sort()
    return rows


def within_24h(cur_step: int, cur_sec: int, old_step: int, old_sec: int) -> bool:
    delta = (cur_step - old_step) * 86400 + (cur_sec - old_sec)
    return 0 <= delta <= 86400


def recent_start(steps: list[int], cur_step: int, window: int) -> int:
    start = len(steps)
    limit = cur_step - window
    while start > 0 and steps[start - 1] >= limit:
        start -= 1
    return start


def build_features(rows):
    customers: dict[str, int] = {}
    merchants: dict[str, int] = {}
    native_names: dict[str, int] = {}
    mapped_names: dict[str, int] = {}
    hist_step: list[list[int]] = []
    hist_sec: list[list[int]] = []
    hist_amt: list[list[float]] = []
    hist_native: list[list[int]] = []
    hist_mapped: list[list[int]] = []
    hist_merch: list[list[int]] = []
    seen_merch: list[set[int]] = []
    totals: list[list[float]] = []
    step_seen: dict[tuple[int, int], int] = {}

    n = len(rows)
    step = np.empty(n, dtype=np.int16)
    y = np.empty(n, dtype=np.int8)
    amount = np.empty(n, dtype=np.float64)
    native = np.empty(n, dtype=np.int16)
    mapped = np.empty(n, dtype=np.int16)
    numeric = np.empty((n, 11), dtype=np.float64)
    names = [
        "log_amount", "prior_count", "amount_over_mean", "customer_z", "new_merchant",
        "days_since", "dup_merchant", "dup_mapped_category", "ratio_30d_mapped",
        "doc_mapped", "safe_dup_count",
    ]

    def code(table: dict[str, int], value: str) -> int:
        if value not in table:
            table[value] = len(table)
        return table[value]

    for index, (raw_step, _order, customer, merchant, category, raw_amount, label) in enumerate(rows):
        cust = code(customers, customer)
        merch = code(merchants, merchant)
        native_code = code(native_names, category)
        mapped_code = code(mapped_names, MAPPED.get(category, "other"))
        if cust == len(hist_step):
            hist_step.append([])
            hist_sec.append([])
            hist_amt.append([])
            hist_native.append([])
            hist_mapped.append([])
            hist_merch.append([])
            seen_merch.append(set())
            totals.append([0.0, 0.0, 0.0])
        sec = step_seen.get((cust, raw_step), 0)
        step_seen[(cust, raw_step)] = sec + 1
        steps = hist_step[cust]
        start = recent_start(steps, raw_step, 30)
        count, total, total_sq = totals[cust]
        mean = total / count if count else 0.0
        variance = max(0.0, total_sq / count - mean * mean) if count else 0.0
        std = variance ** 0.5
        customer_z = (raw_amount - mean) / std if count >= 5 and std > 1e-8 else 0.0
        dup_merchant = 0.0
        dup_mapped = 0.0
        safe_count = 0.0
        mapped_window = []
        for pos in range(start, len(steps)):
            if not within_24h(raw_step, sec, steps[pos], hist_sec[cust][pos]):
                continue
            same_amount = hist_amt[cust][pos] == raw_amount
            if same_amount and hist_merch[cust][pos] == merch:
                dup_merchant = 1.0
            if same_amount and hist_mapped[cust][pos] == mapped_code:
                dup_mapped = 1.0
                safe_count += 1.0
        for pos in range(start, len(steps)):
            if hist_mapped[cust][pos] == mapped_code:
                mapped_window.append(hist_amt[cust][pos])
        if mapped_window:
            median = float(np.median(mapped_window))
            ratio = raw_amount / median if median > 0 else 0.0
            doc = 1.0 if raw_amount > 100 and raw_amount > 3 * median else 0.0
        else:
            ratio = 0.0
            doc = 0.0
        step[index] = raw_step
        y[index] = label
        amount[index] = raw_amount
        native[index] = native_code
        mapped[index] = mapped_code
        numeric[index] = (
            np.log1p(raw_amount),
            count,
            raw_amount / mean if count and mean > 0 else 0.0,
            customer_z,
            0.0 if merch in seen_merch[cust] else 1.0,
            float(raw_step - steps[-1]) if steps else 0.0,
            dup_merchant,
            dup_mapped,
            ratio,
            doc,
            min(20.0, safe_count),
        )
        steps.append(raw_step)
        hist_sec[cust].append(sec)
        hist_amt[cust].append(raw_amount)
        hist_native[cust].append(native_code)
        hist_mapped[cust].append(mapped_code)
        hist_merch[cust].append(merch)
        seen_merch[cust].add(merch)
        totals[cust] = [count + 1, total + raw_amount, total_sq + raw_amount * raw_amount]
        if index and index % 100000 == 0:
            print(f"features {index}", flush=True)
    return {
        "step": step,
        "y": y,
        "amount": amount,
        "native": native,
        "mapped": mapped,
        "numeric": numeric,
        "numeric_names": names,
        "native_names": {code: name for name, code in native_names.items()},
        "mapped_names": {code: name for name, code in mapped_names.items()},
        "customer_count": len(customers),
        "merchant_count": len(merchants),
    }


def masks(step: np.ndarray):
    return step <= TRAIN_MAX, (step > TRAIN_MAX) & (step <= VAL_MAX), step > VAL_MAX


def confusion(y: np.ndarray, pred: np.ndarray) -> dict:
    pred = pred.astype(bool)
    truth = y.astype(bool)
    tp = int(np.sum(pred & truth))
    fp = int(np.sum(pred & ~truth))
    tn = int(np.sum(~pred & ~truth))
    fn = int(np.sum(~pred & truth))
    return {"TP": tp, "FP": fp, "TN": tn, "FN": fn}


def ratios(counts: dict) -> dict:
    tp, fp, tn, fn = counts["TP"], counts["FP"], counts["TN"], counts["FN"]
    total = tp + fp + tn + fn

    def divide(num, den):
        return None if den == 0 else num / den

    precision = divide(tp, tp + fp)
    recall = divide(tp, tp + fn)
    f1 = None if precision is None or recall is None or precision + recall == 0 else (
        2 * precision * recall / (precision + recall)
    )
    return {
        **counts,
        "n": total,
        "alert_rate": divide(tp + fp, total),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "fpr": divide(fp, fp + tn),
    }


def average_precision(y: np.ndarray, score: np.ndarray) -> float:
    if y.sum() == 0:
        return 0.0
    return float(average_precision_score(y, score))


def best_f1_threshold(y: np.ndarray, score: np.ndarray) -> float:
    precision, recall, thresholds = precision_recall_curve(y, score)
    if len(thresholds) == 0:
        return float(np.max(score))
    f1 = np.zeros_like(thresholds)
    usable = (precision[:-1] + recall[:-1]) > 0
    f1[usable] = 2 * precision[:-1][usable] * recall[:-1][usable] / (
        precision[:-1][usable] + recall[:-1][usable]
    )
    return float(thresholds[int(np.argmax(f1))])


def topk_pred(score: np.ndarray, amount: np.ndarray, k: int) -> np.ndarray:
    k = min(max(k, 0), len(score))
    order = np.lexsort((np.arange(len(score)), -amount, -score))
    pred = np.zeros(len(score), dtype=bool)
    pred[order[:k]] = True
    return pred


def fit_logistic(x_train, y_train, x_val, x_test):
    scaler = StandardScaler()
    train = scaler.fit_transform(x_train)
    model = LogisticRegression(
        max_iter=400, class_weight="balanced", solver="lbfgs", random_state=SEED,
    )
    model.fit(train, y_train)
    return (
        model.predict_proba(scaler.transform(x_val))[:, 1],
        model.predict_proba(scaler.transform(x_test))[:, 1],
        model.coef_.ravel(),
        scaler,
    )


def fit_hgb(x_train, y_train, x_val, x_test):
    pos = max(1, int(y_train.sum()))
    neg = max(1, len(y_train) - pos)
    weight = np.where(y_train == 1, 0.5 * len(y_train) / pos, 0.5 * len(y_train) / neg)
    model = HistGradientBoostingClassifier(
        max_iter=80, learning_rate=0.08, max_leaf_nodes=31, min_samples_leaf=40,
        l2_regularization=0.1, random_state=SEED,
    )
    model.fit(x_train, y_train, sample_weight=weight)
    return model.predict_proba(x_val)[:, 1], model.predict_proba(x_test)[:, 1]


def one_hot(codes: np.ndarray, width: int) -> np.ndarray:
    out = np.zeros((len(codes), width), dtype=np.float64)
    valid = (codes >= 0) & (codes < width)
    out[np.arange(len(codes))[valid], codes[valid]] = 1.0
    return out


def amount_bucket(amount: np.ndarray) -> np.ndarray:
    bins = np.array([10, 25, 50, 100, 250], dtype=np.float64)
    return np.searchsorted(bins, amount, side="right").astype(np.float64)


def evaluate_split(y, score, amount, threshold, budgets, prod_k) -> dict:
    return {
        "average_precision": average_precision(y, score),
        "f1_threshold": {
            "threshold": threshold,
            **ratios(confusion(y, score >= threshold)),
        },
        "matched_production_alert_count": ratios(confusion(y, topk_pred(score, amount, prod_k))),
        "review_budgets": {
            str(budget): ratios(confusion(y, topk_pred(score, amount, max(1, int(round(budget * len(y)))))))
            for budget in budgets
        },
    }


def category_breakdown(y, pred, codes, names) -> dict:
    out = {}
    for code, name in names.items():
        chosen = codes == code
        if not np.any(chosen):
            continue
        out[name] = ratios(confusion(y[chosen], pred[chosen]))
    return out


def main() -> None:
    started = time.perf_counter()
    rows = load_rows(SOURCE)
    built = build_features(rows)
    data_seconds = time.perf_counter() - started
    step, y, amount = built["step"], built["y"], built["amount"]
    train, val, test = masks(step)
    numeric = built["numeric"]
    prod = ((amount >= 250) | (numeric[:, 6] >= 1)).astype(np.float64)
    doc_mapped = np.maximum(numeric[:, 9], numeric[:, 7])
    customer_z = numeric[:, 3]
    train_native_width = int(built["native"][train].max()) + 1
    train_mapped_width = int(built["mapped"][train].max()) + 1
    history = numeric[:, [0, 1, 2, 3, 4, 5, 6, 7, 8]]
    safe = np.column_stack([
        amount_bucket(amount),
        numeric[:, 10],
        one_hot(built["mapped"], train_mapped_width),
    ])
    mapped_x = np.column_stack([history, one_hot(built["mapped"], train_mapped_width)])
    native_x = np.column_stack([history, one_hot(built["native"], train_native_width)])
    rates = np.zeros(train_native_width, dtype=np.float64)
    for code in range(train_native_width):
        chosen = train & (built["native"] == code)
        rates[code] = float(y[chosen].mean()) if np.any(chosen) else 0.0
    base_rate = rates[np.clip(built["native"], 0, train_native_width - 1)]

    print("fitting models", flush=True)
    fit_started = time.perf_counter()
    explain_val, explain_test, explain_coef, _scaler = fit_logistic(
        history[train], y[train], history[val], history[test],
    )
    safe_val, safe_test, safe_coef, _safe_scaler = fit_logistic(
        safe[train], y[train], safe[val], safe[test],
    )
    mapped_val, mapped_test, mapped_coef, _mapped_scaler = fit_logistic(
        mapped_x[train], y[train], mapped_x[val], mapped_x[test],
    )
    native_val, native_test, native_coef, _native_scaler = fit_logistic(
        native_x[train], y[train], native_x[val], native_x[test],
    )
    hgb_val, hgb_test = fit_hgb(history[train], y[train], history[val], history[test])
    mapped_hgb_val, mapped_hgb_test = fit_hgb(mapped_x[train], y[train], mapped_x[val], mapped_x[test])
    native_hgb_val, native_hgb_test = fit_hgb(native_x[train], y[train], native_x[val], native_x[test])
    fit_seconds = time.perf_counter() - fit_started

    scores = {
        "prod_rules": (prod[val], prod[test]),
        "doc_rules_mapped": (doc_mapped[val], doc_mapped[test]),
        "amount_score": (amount[val], amount[test]),
        "customer_z": (customer_z[val], customer_z[test]),
        "safe_payload_lr": (safe_val, safe_test),
        "explainable_lr": (explain_val, explain_test),
        "history_hgb": (hgb_val, hgb_test),
        "mapped_lr": (mapped_val, mapped_test),
        "mapped_hgb": (mapped_hgb_val, mapped_hgb_test),
        "category_base_rate": (base_rate[val], base_rate[test]),
        "native_lr": (native_val, native_test),
        "native_hgb": (native_hgb_val, native_hgb_test),
    }
    budgets = (0.005, 0.01, 0.02)
    results = {}
    val_ap = {}
    for name, (val_score, test_score) in scores.items():
        threshold = best_f1_threshold(y[val], val_score)
        prod_k_val = int(np.sum(prod[val] >= 1))
        prod_k_test = int(np.sum(prod[test] >= 1))
        val_ap[name] = average_precision(y[val], val_score)
        results[name] = {
            "pool": "product" if name in SIMPLICITY else "dataset_diagnostic",
            "simplicity": SIMPLICITY.get(name),
            "validation": evaluate_split(y[val], val_score, amount[val], threshold, budgets, prod_k_val),
            "test": evaluate_split(y[test], test_score, amount[test], threshold, budgets, prod_k_test),
        }
        print(name, round(val_ap[name], 4), round(results[name]["test"]["average_precision"], 4), flush=True)

    ranked = sorted(PRODUCT_MODELS, key=lambda name: (-val_ap[name], SIMPLICITY[name]))
    best_ap = val_ap[ranked[0]]
    close = [name for name in ranked if best_ap - val_ap[name] <= 0.01]
    winner = sorted(close, key=lambda name: SIMPLICITY[name])[0]
    winner_score = scores[winner][1]
    winner_threshold = results[winner]["test"]["f1_threshold"]["threshold"]
    prod_k_test = int(np.sum(prod[test] >= 1))
    winner_matched = topk_pred(winner_score, amount[test], prod_k_test)
    prod_pred = prod[test] >= 1
    breakdown = {
        "winner_matched_budget": category_breakdown(
            y[test], winner_matched, built["native"][test], built["native_names"],
        ),
        "production_rules": category_breakdown(
            y[test], prod_pred, built["native"][test], built["native_names"],
        ),
    }
    fn = (~winner_matched) & (y[test] == 1)
    fp = winner_matched & (y[test] == 0)
    payload = {
        "dataset": "BankSim",
        "source_basename": SOURCE.name,
        "rows": int(len(y)),
        "customers": built["customer_count"],
        "merchants": built["merchant_count"],
        "splits": {
            "train_steps": f"0-{TRAIN_MAX}",
            "validation_steps": f"{TRAIN_MAX + 1}-{VAL_MAX}",
            "test_steps": f"{VAL_MAX + 1}-{int(step.max())}",
            "train_rows": int(train.sum()),
            "validation_rows": int(val.sum()),
            "test_rows": int(test.sum()),
            "train_fraud": int(y[train].sum()),
            "validation_fraud": int(y[val].sum()),
            "test_fraud": int(y[test].sum()),
        },
        "selection_rule": (
            "Maximize validation average precision among product-feasible models. "
            "Within 0.01 average precision, choose the simpler model. "
            "Test labels are not used for fitting, thresholds, or selection."
        ),
        "selected_model": winner,
        "validation_average_precision": val_ap,
        "models": results,
        "coefficients": {
            "explainable_lr": dict(zip(built["numeric_names"][:9], [float(v) for v in explain_coef])),
            "safe_payload_lr_head": [float(v) for v in safe_coef[:8]],
            "mapped_lr_history": dict(zip(built["numeric_names"][:9], [float(v) for v in mapped_coef[:9]])),
            "native_lr_history": dict(zip(built["numeric_names"][:9], [float(v) for v in native_coef[:9]])),
        },
        "failure_slices": {
            "winner_matched_false_negatives": int(fn.sum()),
            "winner_matched_false_positives": int(fp.sum()),
            "winner_fn_amount_percentiles": [float(v) for v in np.percentile(amount[test][fn], [10, 50, 90])] if fn.any() else [],
            "winner_fp_amount_percentiles": [float(v) for v in np.percentile(amount[test][fp], [10, 50, 90])] if fp.any() else [],
            "production_alert_count_test": prod_k_test,
            "by_native_category": breakdown,
        },
        "timing_seconds": {
            "load_and_features": data_seconds,
            "model_fit_and_score": fit_seconds,
        },
        "not_called": ["Jev", "Gemini", "Backboard"],
        "assumptions": [
            "BankSim has no currency, direction, clock hour, or subscription flag.",
            "USD, debit, and is_subscription=false are schema assumptions and are not used as learned signals.",
            "Intra-day order is file order. The 24 hour comparison follows core/rules.py.",
            "Train category rates and one-hot columns use training steps only.",
            "Native-category models can see simulator labels that the current product map collapses to other.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({
        "winner": winner,
        "test_rows": payload["splits"]["test_rows"],
        "test_fraud": payload["splits"]["test_fraud"],
        "val_ap": {name: round(val_ap[name], 4) for name in PRODUCT_MODELS},
        "test_ap": {name: round(results[name]["test"]["average_precision"], 4) for name in list(scores)},
        "seconds": round(time.perf_counter() - started, 1),
    }, indent=2))


if __name__ == "__main__":
    main()
