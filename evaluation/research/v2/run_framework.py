"""Isolated BankSim fraud-framework experiment. Does not import production code.

Protocol, frozen before any validation or test metric is read:

TRAIN steps 0-119. Fit models and category or merchant statistics here only.
SELECT steps 120-134. Maximize average precision. Within 0.01 AP, prefer a
model that does not use train-period merchant fraud rate, then fewer feature
groups, then higher recall at this slice's production-rule alert count.
CONFIRM steps 135-149. Scored only by --final. It cannot change the winner.
TEST steps 150-179. Scored only by --final, once. Previously inspected by
PR #14, so it is a comparison holdout, not a pristine blind test.

The same HistGradientBoosting hyperparameters as PR #14 are used for every
boosting model. The experiment changes features and the training objective,
not a large hyperparameter search. Age, gender, zip, and raw customer or
merchant identifiers are not model features.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

SEED = 20261017
TRAIN_MAX = 119
SELECT_MAX = 134
CONFIRM_MAX = 149
SOURCE = Path("/tmp/tl-eval-data/banks.csv")
SPARKOV = Path("/tmp/tl-eval-data/fraudTrain.csv")
PRIOR_JSON = Path(__file__).resolve().parents[1] / "results" / "architecture_benchmark.json"
OUT_DIR = Path(__file__).resolve().parent
MAPPED = {
    "es_barsandrestaurants": "dining",
    "es_food": "groceries",
    "es_hyper": "groceries",
    "es_transportation": "transportation",
    "es_tech": "electronics",
}
HGB_PARAMS = {
    "max_iter": 80,
    "learning_rate": 0.08,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 40,
    "l2_regularization": 0.1,
    "random_state": SEED,
}
MERCHANT_ALPHA = 20.0
AP_BAND = 0.01
MERCHANT_VAL_GATE = 0.02
MERCHANT_CONFIRM_GATE = 0.01
FIXED_BUDGETS = (459, 919, 1113, 1838)
SELECTION_RULE = (
    "Maximize average precision on steps 120-134. Within 0.01 AP, prefer no "
    "train-period merchant fraud rate, then fewer feature groups, then higher "
    "recall at the selection-slice production alert count. Confirm and test "
    "labels are not used to choose the winner or the hyperparameters."
)


def load_rows(path: Path):
    rows = []
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = [cell.strip() for cell in next(reader)]
        expected = [
            "step", "customer", "age", "gender", "zipcodeOri", "merchant",
            "zipMerchant", "category", "amount", "fraud",
        ]
        if header[:10] != expected:
            raise SystemExit(f"Unexpected BankSim header: {header}")
        for index, row in enumerate(reader):
            row = [cell.strip().strip("'") for cell in row]
            if row[9] not in {"0", "1"}:
                raise SystemExit("Fraud label was not 0 or 1")
            rows.append((int(row[0]), index, row[1], row[5], row[7], float(row[8]), int(row[9])))
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
    """Past-only customer history. Category and merchant rates are added later."""
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
    names = [
        "log_amount", "prior_count", "amount_over_mean", "customer_z", "new_merchant",
        "days_since", "dup_merchant", "dup_mapped_category", "ratio_30d_mapped",
        "doc_mapped", "safe_dup_count", "dup_native", "vel_same_step", "vel_7",
        "personal_median_ratio_30",
    ]
    n = len(rows)
    step = np.empty(n, dtype=np.int16)
    y = np.empty(n, dtype=np.int8)
    amount = np.empty(n, dtype=np.float64)
    native = np.empty(n, dtype=np.int16)
    mapped = np.empty(n, dtype=np.int16)
    customer = np.empty(n, dtype=np.int32)
    merchant = np.empty(n, dtype=np.int32)
    numeric = np.empty((n, len(names)), dtype=np.float64)

    def code(table: dict[str, int], value: str) -> int:
        found = table.get(value)
        if found is None:
            found = len(table)
            table[value] = found
        return found

    for index, (raw_step, _order, cust_raw, merch_raw, category, raw_amount, label) in enumerate(rows):
        cust = code(customers, cust_raw)
        merch = code(merchants, merch_raw)
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
        start7 = recent_start(steps, raw_step, 7)
        count, total, total_sq = totals[cust]
        mean = total / count if count else 0.0
        variance = max(0.0, total_sq / count - mean * mean) if count else 0.0
        std = variance ** 0.5
        customer_z = (raw_amount - mean) / std if count >= 5 and std > 1e-8 else 0.0
        dup_merchant = 0.0
        dup_mapped = 0.0
        dup_native = 0.0
        safe_count = 0.0
        mapped_window = []
        for pos in range(start, len(steps)):
            if hist_mapped[cust][pos] == mapped_code:
                mapped_window.append(hist_amt[cust][pos])
            if not within_24h(raw_step, sec, steps[pos], hist_sec[cust][pos]):
                continue
            same_amount = hist_amt[cust][pos] == raw_amount
            if same_amount and hist_merch[cust][pos] == merch:
                dup_merchant = 1.0
            if same_amount and hist_mapped[cust][pos] == mapped_code:
                dup_mapped = 1.0
                safe_count += 1.0
            if same_amount and hist_native[cust][pos] == native_code:
                dup_native = 1.0
        if mapped_window:
            median = float(np.median(mapped_window))
            ratio = raw_amount / median if median > 0 else 0.0
            doc = 1.0 if raw_amount > 100 and raw_amount > 3 * median else 0.0
        else:
            ratio = 0.0
            doc = 0.0
        window_amounts = hist_amt[cust][start:]
        if window_amounts:
            personal_median = float(np.median(window_amounts))
            personal_ratio = raw_amount / personal_median if personal_median > 0 else 0.0
        else:
            personal_ratio = 1.0
        vel_7 = float(len(steps) - start7)
        vel_same = float(sum(1 for pos in range(start7, len(steps)) if steps[pos] == raw_step))
        step[index] = raw_step
        y[index] = label
        amount[index] = raw_amount
        native[index] = native_code
        mapped[index] = mapped_code
        customer[index] = cust
        merchant[index] = merch
        numeric[index] = (
            np.log1p(raw_amount), count, raw_amount / mean if count and mean > 0 else 0.0,
            customer_z, 0.0 if merch in seen_merch[cust] else 1.0,
            float(raw_step - steps[-1]) if steps else 0.0, dup_merchant, dup_mapped,
            ratio, doc, min(20.0, safe_count), dup_native, vel_same, vel_7, personal_ratio,
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
        "customer": customer,
        "merchant": merchant,
        "numeric": numeric,
        "numeric_names": names,
        "native_names": {code: name for name, code in native_names.items()},
        "mapped_names": {code: name for name, code in mapped_names.items()},
        "customer_count": len(customers),
        "merchant_count": len(merchants),
    }


def add_train_references(built, train: np.ndarray):
    """Category CDF uses legitimate training amounts only. Rates use train labels only."""
    native = built["native"]
    amount = built["amount"]
    y = built["y"]
    merchant = built["merchant"]
    width = int(native[train].max()) + 1
    cdf = np.full(len(amount), 0.5, dtype=np.float64)
    ratio = np.ones(len(amount), dtype=np.float64)
    cat_rate = np.full(len(amount), float(y[train].mean()), dtype=np.float64)
    for code in range(width):
        member = native == code
        legit = train & member & (y == 0)
        seen = train & member
        vals = np.sort(amount[legit])
        if len(vals):
            median = float(np.median(vals))
            idx = np.flatnonzero(member)
            cdf[idx] = np.searchsorted(vals, amount[idx], side="right") / len(vals)
            if median > 0:
                ratio[idx] = amount[idx] / median
        if np.any(seen):
            cat_rate[member] = float(y[seen].mean())
    n_merch = int(merchant.max()) + 1
    counts = np.bincount(merchant[train], minlength=n_merch).astype(np.float64)
    frauds = np.bincount(merchant[train], weights=y[train], minlength=n_merch).astype(np.float64)
    global_rate = float(y[train].mean())
    shrunk = (frauds + MERCHANT_ALPHA * global_rate) / (counts + MERCHANT_ALPHA)
    legit_median = np.ones(n_merch, dtype=np.float64)
    for code in range(n_merch):
        vals = amount[train & (merchant == code) & (y == 0)]
        if len(vals):
            legit_median[code] = float(np.median(vals))
    behavior = np.ones(len(amount), dtype=np.float64)
    known = counts[merchant] > 0
    safe_median = np.maximum(legit_median[merchant], 1e-8)
    behavior[known] = amount[known] / safe_median[known]
    fraud_counts = np.bincount(merchant[train & (y == 1)], minlength=n_merch)
    top5 = np.sort(fraud_counts)[-min(5, n_merch):].sum() if n_merch else 0
    built["cat_cdf"] = cdf
    built["amount_over_cat_median"] = ratio
    built["cat_rate"] = cat_rate
    built["merchant_rate"] = shrunk[merchant]
    built["merchant_legit_ratio"] = behavior
    built["merchant_train_count"] = counts[merchant]
    built["train_merchant_fraud_top5_share"] = float(top5 / max(1, fraud_counts.sum()))
    built["train_merchants_with_fraud"] = int(np.sum(fraud_counts > 0))
    built["train_category_width"] = width
    built["train_mapped_width"] = int(built["mapped"][train].max()) + 1
    return built


def masks(step: np.ndarray):
    train = step <= TRAIN_MAX
    select = (step > TRAIN_MAX) & (step <= SELECT_MAX)
    confirm = (step > SELECT_MAX) & (step <= CONFIRM_MAX)
    test = step > CONFIRM_MAX
    return train, select, confirm, test


def one_hot(codes: np.ndarray, width: int) -> np.ndarray:
    out = np.zeros((len(codes), width), dtype=np.float64)
    valid = (codes >= 0) & (codes < width)
    rows = np.arange(len(codes))[valid]
    out[rows, codes[valid]] = 1.0
    return out


def confusion(y: np.ndarray, pred: np.ndarray) -> dict:
    pred = pred.astype(bool)
    truth = y.astype(bool)
    tp = int(np.sum(pred & truth))
    fp = int(np.sum(pred & ~truth))
    tn = int(np.sum(~pred & ~truth))
    fn = int(np.sum(~pred & truth))
    total = tp + fp + tn + fn

    def divide(num, den):
        return None if den == 0 else num / den

    precision = divide(tp, tp + fp)
    recall = divide(tp, tp + fn)
    specificity = divide(tn, tn + fp)
    f1 = None
    if precision is not None and recall is not None and precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    balanced = None
    if recall is not None and specificity is not None:
        balanced = 0.5 * (recall + specificity)
    return {
        "TP": tp, "FP": fp, "TN": tn, "FN": fn, "n": total,
        "alerts": tp + fp,
        "accuracy": divide(tp + tn, total),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "fpr": divide(fp, fp + tn),
        "balanced_accuracy": balanced,
    }


def average_precision(y: np.ndarray, score: np.ndarray) -> float:
    if int(y.sum()) == 0 or len(np.unique(score)) == 1 and int(y.sum()) == len(y):
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
    k = min(max(int(k), 0), len(score))
    order = np.lexsort((np.arange(len(score)), -amount, -score))
    pred = np.zeros(len(score), dtype=bool)
    pred[order[:k]] = True
    return pred


def sample_weight(y: np.ndarray, mode: str):
    if mode == "none":
        return None
    pos = max(1, int(y.sum()))
    neg = max(1, len(y) - pos)
    w_pos = 0.5 * len(y) / pos
    w_neg = 0.5 * len(y) / neg
    if mode == "sqrt":
        w_pos **= 0.5
        w_neg **= 0.5
    elif mode != "balanced":
        raise ValueError(mode)
    return np.where(y == 1, w_pos, w_neg).astype(np.float64)


def fit_hgb(x_train, y_train, x_parts, weight_mode, categorical=None):
    model = HistGradientBoostingClassifier(**HGB_PARAMS)
    if categorical is not None:
        model.set_params(categorical_features=categorical)
    weight = sample_weight(y_train, weight_mode)
    started = time.perf_counter()
    if weight is None:
        model.fit(x_train, y_train)
    else:
        model.fit(x_train, y_train, sample_weight=weight)
    train_seconds = time.perf_counter() - started
    scores = {}
    infer_seconds = 0.0
    infer_rows = 0
    for name, matrix in x_parts.items():
        tick = time.perf_counter()
        scores[name] = model.predict_proba(matrix)[:, 1]
        infer_seconds += time.perf_counter() - tick
        infer_rows += len(matrix)
    return model, scores, train_seconds, infer_seconds, infer_rows


def fit_logistic(x_train, y_train, x_parts):
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("logistic", LogisticRegression(
            max_iter=400, class_weight="balanced", solver="lbfgs", random_state=SEED,
        )),
    ])
    started = time.perf_counter()
    model.fit(x_train, y_train)
    train_seconds = time.perf_counter() - started
    scores = {}
    infer_seconds = 0.0
    infer_rows = 0
    for name, matrix in x_parts.items():
        tick = time.perf_counter()
        scores[name] = model.predict_proba(matrix)[:, 1]
        infer_seconds += time.perf_counter() - tick
        infer_rows += len(matrix)
    return model, scores, train_seconds, infer_seconds, infer_rows


def fit_forest(x_train, y_train, x_parts):
    model = RandomForestClassifier(
        n_estimators=80, max_depth=12, min_samples_leaf=40,
        class_weight="balanced_subsample", random_state=SEED, n_jobs=-1,
    )
    started = time.perf_counter()
    model.fit(x_train, y_train)
    train_seconds = time.perf_counter() - started
    scores = {}
    infer_seconds = 0.0
    infer_rows = 0
    for name, matrix in x_parts.items():
        tick = time.perf_counter()
        scores[name] = model.predict_proba(matrix)[:, 1]
        infer_seconds += time.perf_counter() - tick
        infer_rows += len(matrix)
    return model, scores, train_seconds, infer_seconds, infer_rows


def operating_points(y, score, amount, threshold, prod_k):
    points = {
        "average_precision": average_precision(y, score),
        "f1_threshold": {"threshold": threshold, **confusion(y, score >= threshold)},
        "historical_919": confusion(y, topk_pred(score, amount, 919)),
        "selection_production_alert_count": confusion(y, topk_pred(score, amount, prod_k)),
        "fixed_budgets": {
            str(budget): confusion(y, topk_pred(score, amount, budget)) for budget in FIXED_BUDGETS
        },
    }
    return points


def select_winner(rows):
    best = max(row["val_ap"] for row in rows)
    band = [row for row in rows if best - row["val_ap"] <= AP_BAND]
    band.sort(key=lambda row: (row["merchant"], row["groups"], -row["val_recall_at_prod"], row["name"]))
    return band[0]["name"], best


def recommend(rows, confirm_ap):
    winner, _best = select_winner(rows)
    by_name = {row["name"]: row for row in rows}
    if not by_name[winner]["merchant"]:
        return winner, "The validation winner does not use merchant fraud rate."
    plain_rows = [row for row in rows if not row["merchant"]]
    plain, _plain_best = select_winner(plain_rows)
    gap_val = by_name[winner]["val_ap"] - by_name[plain]["val_ap"]
    gap_confirm = confirm_ap[winner] - confirm_ap[plain]
    if gap_val > MERCHANT_VAL_GATE and gap_confirm > MERCHANT_CONFIRM_GATE:
        return winner, (
            "Merchant-rate model cleared the precommitted gate: "
            f"validation AP gap {gap_val:.4f}, confirm AP gap {gap_confirm:.4f}."
        )
    return plain, (
        "Merchant-rate model did not clear the precommitted gate. "
        f"Validation AP gap {gap_val:.4f}, confirm AP gap {gap_confirm:.4f}. "
        "The deployment recommendation is the best model without that feature."
    )


def category_table(y, pred, codes, names):
    out = {}
    for code, name in names.items():
        chosen = codes == code
        if not np.any(chosen):
            continue
        counts = confusion(y[chosen], pred[chosen])
        out[name] = {
            "fraud": int(y[chosen].sum()),
            "TP": counts["TP"], "FP": counts["FP"], "FN": counts["FN"],
            "precision": counts["precision"], "recall": counts["recall"],
        }
    return out


def merchant_support_slices(score, y, train_count):
    out = {}
    for label, mask in (
        ("unseen_in_train", train_count == 0),
        ("fewer_than_20_train_rows", train_count < 20),
        ("at_least_20_train_rows", train_count >= 20),
    ):
        if not np.any(mask) or int(y[mask].sum()) == 0:
            out[label] = {"rows": int(mask.sum()), "fraud": int(y[mask].sum()) if np.any(mask) else 0}
            continue
        out[label] = {
            "rows": int(mask.sum()),
            "fraud": int(y[mask].sum()),
            "average_precision": average_precision(y[mask], score[mask]),
        }
    return out


def reason_counts(chosen, built):
    cdf = built["cat_cdf"][chosen]
    zed = built["numeric"][chosen, 3]
    new_merch = built["numeric"][chosen, 4]
    vel = built["numeric"][chosen, 12]
    amount = built["amount"][chosen]
    return {
        "alerts": int(len(chosen)),
        "amount_at_least_250": int(np.sum(amount >= 250)),
        "category_cdf_at_least_0.95": int(np.sum(cdf >= 0.95)),
        "new_merchant": int(np.sum(new_merch >= 1)),
        "customer_z_at_least_3": int(np.sum(zed >= 3)),
        "same_step_velocity_at_least_2": int(np.sum(vel >= 2)),
    }


def permutation_drop(model, matrix, y, names, kind):
    rng = np.random.default_rng(SEED)
    fraud = np.flatnonzero(y == 1)
    legit = np.flatnonzero(y == 0)
    take_legit = min(len(legit), 8000)
    chosen = np.concatenate([fraud, rng.choice(legit, size=take_legit, replace=False)])
    xs = matrix[chosen]
    ys = y[chosen]
    if kind not in {"hgb", "logistic", "forest"}:
        return {}
    base_score = model.predict_proba(xs)[:, 1]
    base = average_precision(ys, base_score)
    drops = {}
    for index, name in enumerate(names):
        shuffled = xs.copy()
        rng.shuffle(shuffled[:, index])
        score = model.predict_proba(shuffled)[:, 1]
        drops[name] = base - average_precision(ys, score)
    return {"sample_rows": int(len(chosen)), "sample_fraud": int(len(fraud)), "base_ap": base, "drop": drops}


def prior_reported():
    if not PRIOR_JSON.exists():
        return {"available": False}
    payload = json.loads(PRIOR_JSON.read_text())
    wanted = {}
    for name in ("prod_rules", "mapped_hgb", "native_hgb", "amount_score"):
        model = payload["models"][name]
        wanted[name] = {
            "test_average_precision": model["test"]["average_precision"],
            "test_matched_production_alert_count": model["test"]["matched_production_alert_count"],
            "test_f1_threshold": model["test"]["f1_threshold"],
        }
    return {
        "available": True,
        "source": "evaluation/research/results/architecture_benchmark.json",
        "label": "Previously reported by PR #14. Not a measurement from this run.",
        "selected_model": payload["selected_model"],
        "models": wanted,
    }


def sparkov_provenance():
    """Reject the local export unless it matches the official Sparkov description."""
    if not SPARKOV.exists():
        return {"present": False, "used_for_training": False}
    size = SPARKOV.stat().st_size
    with SPARKOV.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        first = next(reader)
    cc = first[2] if len(first) > 2 else ""
    scientific = "e+" in cc.lower()
    rows = 0
    fraud = 0
    tmin = None
    tmax = None
    with SPARKOV.open(newline="") as handle:
        reader = csv.reader(handle)
        next(reader)
        for row in reader:
            rows += 1
            if row[22] in {"1", "1.0"}:
                fraud += 1
            stamp = int(float(row[19]))
            tmin = stamp if tmin is None else min(tmin, stamp)
            tmax = stamp if tmax is None else max(tmax, stamp)
    official_clock = tmin is not None and tmin >= 1546300800 and tmax <= 1609459200
    verdict = "OFFICIAL" if rows > 1_048_575 and not scientific and official_clock else "NOT_OFFICIAL"
    return {
        "present": True,
        "bytes": size,
        "rows": rows,
        "fraud": fraud,
        "cc_num_scientific_notation": scientific,
        "unix_min": tmin,
        "unix_max": tmax,
        "excel_row_cap_1048575": rows == 1_048_575,
        "verdict": verdict,
        "used_for_training": False,
        "reason": (
            "Official kartik2112/fraud-detection Sparkov data is described as 2019-2020 "
            "with intact card identifiers. This export is not that file."
            if verdict != "OFFICIAL" else "File matched the official checks."
        ),
    }


def split_counts(y, masks_by_name):
    out = {}
    for name, mask in masks_by_name.items():
        out[name] = {"rows": int(mask.sum()), "fraud": int(y[mask].sum())}
    return out


def latency_ms_per_1k(seconds, rows):
    if rows <= 0:
        return None
    return 1000.0 * seconds / (rows / 1000.0)


def jsonable(value):
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return jsonable(value.tolist())
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def self_check():
    y = np.array([1, 0, 1, 0])
    pred = np.array([1, 1, 0, 0])
    counts = confusion(y, pred)
    assert counts["TP"] == 1 and counts["FP"] == 1 and counts["FN"] == 1 and counts["TN"] == 1
    assert abs(counts["balanced_accuracy"] - 0.5) < 1e-9
    score = np.array([0.2, 0.9, 0.4])
    amount = np.array([5.0, 1.0, 9.0])
    chosen = topk_pred(score, amount, 2)
    assert list(chosen) == [False, True, True]


def evaluate_split_bundle(score, y, amount, threshold, prod_k):
    return operating_points(y, score, amount, threshold, prod_k)


def main():
    self_check()
    final = "--final" in sys.argv
    started = time.perf_counter()
    rows = load_rows(SOURCE)
    built = build_features(rows)
    del rows
    step = built["step"]
    y = built["y"]
    amount = built["amount"]
    train, select, confirm, test = masks(step)
    expected = {
        "train": (374_914, 4_800),
        "old_validation_120_149": (108_423, 1_200),
        "test": (111_306, 1_200),
    }
    old_val = (step > TRAIN_MAX) & (step <= CONFIRM_MAX)
    actual = {
        "train": (int(train.sum()), int(y[train].sum())),
        "old_validation_120_149": (int(old_val.sum()), int(y[old_val].sum())),
        "test": (int(test.sum()), int(y[test].sum())),
    }
    if actual != expected:
        raise SystemExit(f"BankSim population changed: {actual} != {expected}")
    built = add_train_references(built, train)
    numeric = built["numeric"]
    native_width = built["train_category_width"]
    mapped_width = built["train_mapped_width"]
    native_oh = one_hot(built["native"], native_width)
    mapped_oh = one_hot(built["mapped"], mapped_width)
    hist9 = numeric[:, :9]
    v2_cols = [0, 1, 2, 3, 4, 5, 6, 11, 12, 13, 14]
    v2_names = [built["numeric_names"][i] for i in v2_cols] + [
        "cat_cdf", "amount_over_cat_median",
    ]
    enriched_num = np.column_stack([
        numeric[:, v2_cols], built["cat_cdf"], built["amount_over_cat_median"],
    ])
    no_cdf_num = numeric[:, v2_cols]
    no_hist_num = np.column_stack([
        numeric[:, 0], built["cat_cdf"], built["amount_over_cat_median"],
    ])
    matrices = {
        "pr14_mapped": np.column_stack([hist9, mapped_oh]),
        "native": np.column_stack([hist9, native_oh]),
        "native_cat": np.column_stack([hist9, built["native"].astype(np.float64)]),
        "public": np.column_stack([numeric[:, 0], native_oh]),
        "no_history": np.column_stack([no_hist_num, native_oh]),
        "no_cdf": np.column_stack([no_cdf_num, native_oh]),
        "enriched": np.column_stack([enriched_num, native_oh]),
        "merchant": np.column_stack([enriched_num, built["merchant_rate"], native_oh]),
        "merchant_behavior": np.column_stack([
            enriched_num, built["merchant_legit_ratio"], native_oh,
        ]),
    }
    feature_names = {
        "pr14_mapped": built["numeric_names"][:9] + [f"mapped_{built['mapped_names'][i]}" for i in range(mapped_width)],
        "native": built["numeric_names"][:9] + [f"native_{built['native_names'].get(i, i)}" for i in range(native_width)],
        "public": ["log_amount"] + [f"native_{built['native_names'].get(i, i)}" for i in range(native_width)],
        "no_history": ["log_amount", "cat_cdf", "amount_over_cat_median"] + [
            f"native_{built['native_names'].get(i, i)}" for i in range(native_width)
        ],
        "no_cdf": [built["numeric_names"][i] for i in v2_cols] + [
            f"native_{built['native_names'].get(i, i)}" for i in range(native_width)
        ],
        "enriched": v2_names + [f"native_{built['native_names'].get(i, i)}" for i in range(native_width)],
        "merchant": v2_names + ["merchant_rate"] + [
            f"native_{built['native_names'].get(i, i)}" for i in range(native_width)
        ],
        "merchant_behavior": v2_names + ["merchant_legit_amount_ratio"] + [
            f"native_{built['native_names'].get(i, i)}" for i in range(native_width)
        ],
        "native_cat": built["numeric_names"][:9] + ["native_category_code"],
    }
    requested = ("select",) if not final else ("select", "confirm", "test")
    split_idx = {"select": select, "confirm": confirm, "test": test}
    parts_for = lambda key: {name: matrices[key][split_idx[name]] for name in requested}

    specs = []
    stored_models = {}
    full_scores = {}
    timings = {}

    def stash(name, groups, merchant, family, scores, train_seconds, infer_seconds, infer_rows, model=None):
        full = np.full(len(y), np.nan, dtype=np.float64)
        for split_name, values in scores.items():
            full[split_idx[split_name]] = values
        if not np.isfinite(full[select]).all():
            raise SystemExit(f"{name} produced non-finite selection scores")
        full_scores[name] = full
        timings[name] = {
            "training_seconds": train_seconds,
            "inference_seconds": infer_seconds,
            "inference_rows": infer_rows,
            "inference_ms_per_1k_rows": latency_ms_per_1k(infer_seconds, infer_rows),
        }
        specs.append({"name": name, "groups": groups, "merchant": merchant, "family": family})
        if model is not None:
            stored_models[name] = model
        print(name, "select_ap", round(average_precision(y[select], full[select]), 4), flush=True)

    prod = ((amount >= 250) | (numeric[:, 6] >= 1)).astype(np.float64)
    stash("prod_rules", 1, False, "rules", {name: prod[split_idx[name]] for name in requested}, 0.0, 0.0, 0)
    stash("amount_score", 1, False, "score", {name: amount[split_idx[name]] for name in requested}, 0.0, 0.0, 0)
    stash("cdf_only", 1, False, "score", {name: built["cat_cdf"][split_idx[name]] for name in requested}, 0.0, 0.0, 0)
    rate_cdf = built["cat_rate"] * built["cat_cdf"]
    stash("rate_times_cdf", 2, False, "score", {name: rate_cdf[split_idx[name]] for name in requested}, 0.0, 0.0, 0)

    learners = [
        ("public_lr", "public", 2, False, "logistic", "none", None),
        ("public_rf", "public", 2, False, "forest", "none", None),
        ("pr14_mapped_hgb", "pr14_mapped", 2, False, "hgb", "balanced", None),
        ("native_hgb_weighted", "native", 2, False, "hgb", "balanced", None),
        ("native_hgb_plain", "native", 2, False, "hgb", "none", None),
        ("native_hgb_categorical", "native_cat", 2, False, "hgb", "none", [9]),
        ("v2_no_history", "no_history", 2, False, "hgb", "none", None),
        ("v2_no_cdf", "no_cdf", 2, False, "hgb", "none", None),
        ("v2_enriched", "enriched", 3, False, "hgb", "none", None),
        ("v2_enriched_weighted", "enriched", 3, False, "hgb", "balanced", None),
        ("v2_enriched_sqrt", "enriched", 3, False, "hgb", "sqrt", None),
        ("v2_merchant", "merchant", 4, True, "hgb", "none", None),
        ("v2_merchant_behavior", "merchant_behavior", 4, False, "hgb", "none", None),
    ]
    for name, key, groups, merchant_flag, family, weight_mode, categorical in learners:
        matrix = matrices[key]
        if family == "hgb":
            model, scores, train_s, infer_s, infer_n = fit_hgb(
                matrix[train], y[train], parts_for(key), weight_mode, categorical,
            )
        elif family == "logistic":
            model, scores, train_s, infer_s, infer_n = fit_logistic(matrix[train], y[train], parts_for(key))
        else:
            model, scores, train_s, infer_s, infer_n = fit_forest(matrix[train], y[train], parts_for(key))
        stash(name, groups, merchant_flag, family, scores, train_s, infer_s, infer_n, model)

    plain = full_scores["native_hgb_plain"]
    cdf = full_scores["cdf_only"]
    blend = 0.5 * (plain + cdf)
    both = np.maximum(plain, cdf)
    stash("blend_plain_cdf", 3, False, "blend", {name: blend[split_idx[name]] for name in requested}, 0.0, 0.0, 0)
    stash("max_plain_cdf", 3, False, "blend", {name: both[split_idx[name]] for name in requested}, 0.0, 0.0, 0)

    prod_k_select = int(np.sum(prod[select] >= 1))
    threshold_source = {}
    ranking_rows = []
    select_metrics = {}
    for spec in specs:
        name = spec["name"]
        score = full_scores[name][select]
        threshold = best_f1_threshold(y[select], score)
        threshold_source[name] = threshold
        point = confusion(y[select], topk_pred(score, amount[select], prod_k_select))
        ap = average_precision(y[select], score)
        ranking_rows.append({
            "name": name,
            "groups": spec["groups"],
            "merchant": spec["merchant"],
            "family": spec["family"],
            "val_ap": ap,
            "val_recall_at_prod": point["recall"] or 0.0,
        })
        select_metrics[name] = evaluate_split_bundle(score, y[select], amount[select], threshold, prod_k_select)
    winner, best_ap = select_winner(ranking_rows)
    print("selection_winner", winner, "best_ap", round(best_ap, 4), flush=True)

    payload = {
        "dataset": "BankSim",
        "source_basename": SOURCE.name,
        "stage": "final" if final else "validation_only",
        "population_check": actual,
        "splits": {
            "train": "0-119",
            "selection": "120-134",
            "confirm": "135-149",
            "test": "150-179",
            "counts": split_counts(y, {
                "train": train, "selection": select, "confirm": confirm, "test": test,
            }),
            "test_limit": (
                "Steps 150-179 were already inspected by PR #14. "
                "This run uses them for direct comparison only. They are not a pristine blind test. "
                "No earlier BankSim time slice remains untouched."
            ),
        },
        "selection_rule": SELECTION_RULE,
        "ap_band": AP_BAND,
        "selected_model": winner,
        "selection_slice_production_alerts": prod_k_select,
        "validation_ranking": ranking_rows,
        "selection_metrics": select_metrics,
        "hgb_hyperparameters": HGB_PARAMS,
        "merchant_shrinkage_alpha": MERCHANT_ALPHA,
        "fixed_budgets": list(FIXED_BUDGETS),
        "excluded_features": ["age", "gender", "zipcodeOri", "zipMerchant", "raw_customer_id", "raw_merchant_id"],
        "not_called": ["Jev", "Gemini", "Backboard"],
        "previously_reported_pr14": prior_reported(),
        "timing_seconds": {"load_and_history_features": time.perf_counter() - started},
    }
    OUT_DIR.joinpath("results").mkdir(parents=True, exist_ok=True)
    if not final:
        path = OUT_DIR / "results" / "framework_v2_val.json"
        path.write_text(json.dumps(jsonable(payload), indent=2) + "\n")
        print(json.dumps({
            "stage": "validation_only",
            "winner": winner,
            "ranking": [
                {"name": row["name"], "ap": round(row["val_ap"], 4), "merchant": row["merchant"]}
                for row in sorted(ranking_rows, key=lambda item: -item["val_ap"])
            ],
        }, indent=2))
        return

    confirm_ap = {}
    confirm_metrics = {}
    test_metrics = {}
    prod_k_confirm = int(np.sum(prod[confirm] >= 1))
    prod_k_test = int(np.sum(prod[test] >= 1))
    for spec in specs:
        name = spec["name"]
        threshold = threshold_source[name]
        confirm_score = full_scores[name][confirm]
        test_score = full_scores[name][test]
        confirm_ap[name] = average_precision(y[confirm], confirm_score)
        confirm_metrics[name] = evaluate_split_bundle(
            confirm_score, y[confirm], amount[confirm], threshold, prod_k_confirm,
        )
        test_metrics[name] = evaluate_split_bundle(
            test_score, y[test], amount[test], threshold, prod_k_test,
        )
    recommended, recommendation_reason = recommend(ranking_rows, confirm_ap)
    winner_pred = topk_pred(full_scores[winner][test], amount[test], 919)
    recommended_pred = topk_pred(full_scores[recommended][test], amount[test], 919)
    pr14_pred = topk_pred(full_scores["pr14_mapped_hgb"][test], amount[test], 919)
    prod_pred = prod[test] >= 1
    truth = y[test] == 1

    def disagreement(left, right):
        return {
            "both_correct": int(np.sum(left & right & truth)),
            "only_left": int(np.sum(left & ~right & truth)),
            "only_right": int(np.sum(~left & right & truth)),
            "neither": int(np.sum(~left & ~right & truth)),
        }

    analysis_name = recommended
    analysis_pred = recommended_pred
    fn = (~analysis_pred) & truth
    fp = analysis_pred & ~truth
    names = built["native_names"]
    importance = {}
    model = stored_models.get(analysis_name)
    family = next(spec["family"] for spec in specs if spec["name"] == analysis_name)
    matrix_key = {
        "public_lr": "public", "public_rf": "public", "pr14_mapped_hgb": "pr14_mapped",
        "native_hgb_weighted": "native", "native_hgb_plain": "native",
        "native_hgb_categorical": "native_cat", "v2_no_history": "no_history",
        "v2_no_cdf": "no_cdf", "v2_enriched": "enriched", "v2_enriched_weighted": "enriched",
        "v2_enriched_sqrt": "enriched", "v2_merchant": "merchant",
        "v2_merchant_behavior": "merchant_behavior",
    }.get(analysis_name)
    if model is not None and matrix_key is not None and family in {"hgb", "logistic", "forest"}:
        importance = permutation_drop(
            model, matrices[matrix_key][select], y[select], feature_names[matrix_key], family,
        )
    unseen = np.isin(built["customer"][test], built["customer"][train], invert=True)
    unseen_budget = int(round(919 * unseen.sum() / max(1, test.sum())))
    model_path = OUT_DIR / "models" / "recommended.joblib"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "recommended_model": recommended,
        "selected_model": winner,
        "hgb_hyperparameters": HGB_PARAMS,
        "selection_threshold": threshold_source[recommended],
        "feature_note": "Re-fit with this script. The artifact is the fitted estimator when one exists.",
        "estimator": model if model is not None else None,
    }
    joblib.dump(artifact, model_path)
    payload.update({
        "recommended_model": recommended,
        "recommendation_reason": recommendation_reason,
        "confirm_average_precision": confirm_ap,
        "confirm_metrics": confirm_metrics,
        "test_metrics": test_metrics,
        "test_production_alert_count": prod_k_test,
        "timings": timings,
        "customer_count": built["customer_count"],
        "merchant_count": built["merchant_count"],
        "sparkov_provenance": sparkov_provenance(),
        "failure_analysis_at_919": {
            "model": analysis_name,
            "false_negatives": int(fn.sum()),
            "false_positives": int(fp.sum()),
            "fn_amount_percentiles": [float(v) for v in np.percentile(amount[test][fn], [10, 50, 90])] if fn.any() else [],
            "fp_amount_percentiles": [float(v) for v in np.percentile(amount[test][fp], [10, 50, 90])] if fp.any() else [],
            "fn_category_cdf_below_0.90": int(np.sum(built["cat_cdf"][test][fn] < 0.90)) if fn.any() else 0,
            "fn_new_merchant": int(np.sum(numeric[test][fn, 4] >= 1)) if fn.any() else 0,
            "by_native_category": category_table(y[test], analysis_pred, built["native"][test], names),
            "production_by_native_category": category_table(y[test], prod_pred, built["native"][test], names),
            "pr14_by_native_category": category_table(y[test], pr14_pred, built["native"][test], names),
            "reason_codes_on_alerts": reason_counts(np.flatnonzero(test)[analysis_pred], built),
            "fraud_overlap_recommended_vs_pr14": disagreement(recommended_pred, pr14_pred),
            "fraud_overlap_recommended_vs_rules": disagreement(recommended_pred, prod_pred),
            "fraud_overlap_selected_vs_pr14": disagreement(winner_pred, pr14_pred),
        },
        "merchant_support_diagnostic": {
            "label": (
                "Precommitted. Not used to change the winner. "
                "Average precision by how often the merchant appeared in training."
            ),
            "train_merchants_with_fraud": built["train_merchants_with_fraud"],
            "train_fraud_share_in_top5_merchants": built["train_merchant_fraud_top5_share"],
            "slices": {
                name: merchant_support_slices(full_scores[name][test], y[test], built["merchant_train_count"][test])
                for name in ("v2_merchant", "v2_merchant_behavior", recommended, "pr14_mapped_hgb")
            },
        },
        "permutation_on_selection_sample": importance,
        "unseen_customer_test_slice": {
            "label": "Same previously inspected steps 150-179, restricted to customers absent from steps 0-119. Not a new time period.",
            "rows": int(unseen.sum()),
            "fraud": int(y[test][unseen].sum()),
            "average_precision": average_precision(y[test][unseen], full_scores[recommended][test][unseen]) if unseen.any() else None,
            "budget": unseen_budget,
            "budget_counts": confusion(
                y[test][unseen],
                topk_pred(full_scores[recommended][test][unseen], amount[test][unseen], unseen_budget),
            ) if unseen.any() else {},
        },
        "model_artifact": str(model_path),
        "assumptions": [
            "BankSim has no clock hour, currency, direction, or subscription flag.",
            "Production-rule reproduction is amount >= 250 or a same-merchant same-amount duplicate inside 24 hours.",
            "Intra-day order is file order, matching the PR #14 reproduction.",
            "Category amount CDF and category fraud rate are fit on steps 0-119 only.",
            "CDF reference rows are legitimate training transactions, so the reference is not inflated by known fraud.",
            "Merchant fraud rate is shrunk toward the training base rate and is treated as a leakage-risk feature.",
            "Within the training window, the category reference uses the whole window, not an expanding daily window.",
            "Customer history features use only earlier rows.",
        ],
    })
    path = OUT_DIR / "results" / "framework_v2.json"
    path.write_text(json.dumps(jsonable(payload), indent=2) + "\n")
    brief = {
        "winner": winner,
        "recommended": recommended,
        "test_alerts_919": {
            name: {
                "TP": test_metrics[name]["historical_919"]["TP"],
                "FP": test_metrics[name]["historical_919"]["FP"],
                "FN": test_metrics[name]["historical_919"]["FN"],
                "precision": test_metrics[name]["historical_919"]["precision"],
                "recall": test_metrics[name]["historical_919"]["recall"],
                "f1": test_metrics[name]["historical_919"]["f1"],
                "ap": test_metrics[name]["average_precision"],
            }
            for name in ("prod_rules", "pr14_mapped_hgb", recommended, winner)
        },
        "seconds": round(time.perf_counter() - started, 1),
    }
    print(json.dumps(jsonable(brief), indent=2), flush=True)


if __name__ == "__main__":
    main()
