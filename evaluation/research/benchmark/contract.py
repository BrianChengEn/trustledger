"""Frozen BankSim head-to-head contract.

This file was written before any new public-model test score was computed.
It does not train a model and it does not modify production code.

The test slice, steps 150-179, was already inspected by PR #14 and PR #15.
Scores on that slice are a reproducible comparison, not a pristine blind holdout.
Hyperparameters and feature definitions in this file are not chosen from those
test scores.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

V2_DIR = Path(__file__).resolve().parents[1] / "v2"
if str(V2_DIR) not in sys.path:
    sys.path.insert(0, str(V2_DIR))

import run_framework as fw  # noqa: E402

ALERT_BUDGET = 919
TEST_ROWS = 111_306
TEST_FRAUD = 1_200
BUDGET_RATE = ALERT_BUDGET / TEST_ROWS
N_JOBS = 4
N_BOOT = 200
BOOT_SEED = fw.SEED

# Primary leaderboard key. Operating-point F1 is reported, not used to re-rank.
RANK_KEY = "test_average_precision"
SIMILAR_AP = 0.01

AMOUNT_SLICES = (
    ("[0,20)", 0.0, 20.0),
    ("[20,250)", 20.0, 250.0),
    (">=250", 250.0, None),
)

PREVIOUSLY_REPORTED = {
    "source": "evaluation/research/v2/results/framework_v2.json",
    "role": "claims to reproduce, not this run's measurements",
    "models": {
        "prod_rules": {
            "average_precision": 0.45007707926977253,
            "TP": 701, "FP": 218, "TN": 109888, "FN": 499,
        },
        "pr14_mapped_hgb": {
            "average_precision": 0.8153928294023746,
            "TP": 786, "FP": 133, "TN": 109973, "FN": 414,
        },
        "v2_enriched_sqrt": {
            "average_precision": 0.8852597833910728,
            "TP": 837, "FP": 82, "TN": 110024, "FN": 363,
        },
        "v2_merchant": {
            "average_precision": 0.9584845166158367,
            "TP": 892, "FP": 27, "TN": 110079, "FN": 308,
        },
    },
}

ATAVCI_SOURCE = (
    "https://github.com/atavci/fraud-detection-on-banksim-data/blob/master/"
    "Fraud_Detection_bank_sim.py"
)
ATAVCI_DATE = "2019-03-15"
SUSHMITHA_SOURCE = "https://github.com/0xSushmitha/Fraud-detection-in-financial-Transactions"
SUSHMITHA_UNDERsample_RATIO = 0.05
SUSHMITHA_MODELS = 5

XGB_SHARED = {
    "max_depth": 6,
    "learning_rate": 0.05,
    "n_estimators": 400,
    "booster": "gbtree",
    "n_jobs": N_JOBS,
    "gamma": 0,
    "min_child_weight": 1,
    "max_delta_step": 0,
    "subsample": 1,
    "colsample_bytree": 1,
    "colsample_bylevel": 1,
    "reg_alpha": 0,
    "reg_lambda": 1,
    "scale_pos_weight": 1,
    "base_score": 0.5,
    "random_state": 42,
    "verbosity": 0,
}
RF_PARAMS = {
    "n_estimators": 100,
    "max_depth": 8,
    "random_state": 42,
    "class_weight": "balanced",
    "n_jobs": N_JOBS,
    "verbose": 0,
}
LGBM_PARAMS = {
    "n_estimators": 300,
    "learning_rate": 0.07,
    "num_leaves": 63,
    "verbose": -1,
    "n_jobs": N_JOBS,
}


def population_expected():
    return {
        "train": (374_914, 4_800),
        "select": (53_722, 600),
        "confirm": (54_701, 600),
        "test": (TEST_ROWS, TEST_FRAUD),
    }


def assert_population(y, train, select, confirm, test):
    actual = {
        "train": (int(train.sum()), int(y[train].sum())),
        "select": (int(select.sum()), int(y[select].sum())),
        "confirm": (int(confirm.sum()), int(y[confirm].sum())),
        "test": (int(test.sum()), int(y[test].sum())),
    }
    expected = population_expected()
    if actual != expected:
        raise SystemExit(f"BankSim population changed: {actual} != {expected}")
    n_train = int(train.sum())
    if not (train[:n_train].all() and not train[n_train:].any()):
        raise SystemExit("Training mask is not a chronological prefix")
    return actual


def load_aligned_raw(path: Path = fw.SOURCE):
    """CSV rows sorted by (step, file order), the same order as fw.load_rows."""
    records = []
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = [cell.strip().strip("'") for cell in next(reader)]
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
            records.append((
                int(row[0]), index, row[1], row[2], row[3], row[5], row[7],
                float(row[8]), int(row[9]),
            ))
    records.sort()
    columns = {
        "step": np.array([row[0] for row in records], dtype=np.int16),
        "order": np.array([row[1] for row in records], dtype=np.int32),
        "customer": [row[2] for row in records],
        "age": [row[3] for row in records],
        "gender": [row[4] for row in records],
        "merchant": [row[5] for row in records],
        "category": [row[6] for row in records],
        "amount": np.array([row[7] for row in records], dtype=np.float64),
        "fraud": np.array([row[8] for row in records], dtype=np.int8),
    }
    return columns


def load_bundle(path: Path = fw.SOURCE):
    """Feature bundle used by every TrustLedger reproduction in this benchmark."""
    fw.self_check()
    raw = load_aligned_raw(path)
    rows = list(zip(
        raw["step"].tolist(),
        raw["order"].tolist(),
        raw["customer"],
        raw["merchant"],
        raw["category"],
        raw["amount"].tolist(),
        raw["fraud"].tolist(),
    ))
    built = fw.build_features(rows)
    if not np.array_equal(built["y"], raw["fraud"]):
        raise SystemExit("Aligned labels do not match framework features")
    if not np.allclose(built["amount"], raw["amount"]):
        raise SystemExit("Aligned amounts do not match framework features")
    train, select, confirm, test = fw.masks(built["step"])
    assert_population(built["y"], train, select, confirm, test)
    built = fw.add_train_references(built, train)
    built["train"] = train
    built["select"] = select
    built["confirm"] = confirm
    built["test"] = test
    built["raw"] = raw
    return built


def parity_parts(built):
    """Track A matrix: v2 enriched features, no merchant fraud rate, no raw ids."""
    numeric = built["numeric"]
    columns = [0, 1, 2, 3, 4, 5, 6, 11, 12, 13, 14]
    names = [built["numeric_names"][i] for i in columns]
    names += ["cat_cdf", "amount_over_cat_median"]
    native_width = built["train_category_width"]
    native_oh = fw.one_hot(built["native"], native_width)
    enriched = np.column_stack([
        numeric[:, columns], built["cat_cdf"], built["amount_over_cat_median"],
    ])
    names += [f"native_{built['native_names'].get(i, i)}" for i in range(native_width)]
    return np.column_stack([enriched, native_oh]), names, enriched


def pr14_matrix(built):
    mapped_width = built["train_mapped_width"]
    mapped_oh = fw.one_hot(built["mapped"], mapped_width)
    names = built["numeric_names"][:9] + [
        f"mapped_{built['mapped_names'].get(i, i)}" for i in range(mapped_width)
    ]
    return np.column_stack([built["numeric"][:, :9], mapped_oh]), names


def merchant_matrix(built, rate):
    parity, names, enriched = parity_parts(built)
    matrix = np.column_stack([
        enriched, np.asarray(rate, dtype=np.float64), parity[:, enriched.shape[1]:],
    ])
    return matrix, names[: enriched.shape[1]] + ["merchant_rate"] + names[enriched.shape[1]:]


def rules_score(built):
    """Binary production-rule score. Ties break by amount, then row index."""
    amount = built["amount"]
    duplicate = built["numeric"][:, 6] >= 1
    return ((amount >= 250) | duplicate).astype(np.float64)


def _prefix_train_count(train_mask):
    n_train = int(np.asarray(train_mask).sum())
    mask = np.asarray(train_mask, dtype=bool)
    if not (mask[:n_train].all() and not mask[n_train:].any()):
        raise ValueError("train mask must be a chronological prefix")
    return n_train


def step_causal_merchant_rate(merchant, y, step, train_mask, alpha=fw.MERCHANT_ALPHA):
    """Train rows use only earlier steps. Later rows use the frozen train aggregate.

    A row's own label and other labels from the same step are excluded.
    Select, confirm, and test labels are excluded from every rate.
    """
    merchant = np.asarray(merchant)
    y = np.asarray(y, dtype=np.float64)
    step = np.asarray(step)
    n_train = _prefix_train_count(train_mask)
    if np.any(step[:-1] > step[1:]):
        raise ValueError("step must be nondecreasing")
    n_merch = int(merchant.max()) + 1
    rate = np.zeros(len(y), dtype=np.float64)
    counts = np.zeros(n_merch, dtype=np.float64)
    frauds = np.zeros(n_merch, dtype=np.float64)
    g_count = 0.0
    g_fraud = 0.0
    i = 0
    while i < n_train:
        cur = int(step[i])
        j = i + 1
        while j < n_train and int(step[j]) == cur:
            j += 1
        prior = (g_fraud / g_count) if g_count else 0.0
        for t in range(i, j):
            m = int(merchant[t])
            rate[t] = (frauds[m] + alpha * prior) / (counts[m] + alpha)
        for t in range(i, j):
            m = int(merchant[t])
            counts[m] += 1.0
            frauds[m] += y[t]
            g_count += 1.0
            g_fraud += y[t]
        i = j
    global_rate = float(y[:n_train].mean()) if n_train else 0.0
    full_counts = np.bincount(merchant[:n_train], minlength=n_merch).astype(np.float64)
    full_frauds = np.bincount(
        merchant[:n_train], weights=y[:n_train], minlength=n_merch,
    ).astype(np.float64)
    shrunk = (full_frauds + alpha * global_rate) / (full_counts + alpha)
    rate[n_train:] = shrunk[merchant[n_train:]]
    return rate


def expanding_merchant_rate(merchant, y, step, alpha=fw.MERCHANT_ALPHA):
    """Every row uses completed earlier steps only.

    Test rows therefore see select and confirm labels. That is a different
    information set from the PR #15 frozen-train feature. Report it separately.
    """
    merchant = np.asarray(merchant)
    y = np.asarray(y, dtype=np.float64)
    step = np.asarray(step)
    if np.any(step[:-1] > step[1:]):
        raise ValueError("step must be nondecreasing")
    n_merch = int(merchant.max()) + 1
    rate = np.zeros(len(y), dtype=np.float64)
    counts = np.zeros(n_merch, dtype=np.float64)
    frauds = np.zeros(n_merch, dtype=np.float64)
    g_count = 0.0
    g_fraud = 0.0
    i = 0
    n = len(y)
    while i < n:
        cur = int(step[i])
        j = i + 1
        while j < n and int(step[j]) == cur:
            j += 1
        prior = (g_fraud / g_count) if g_count else 0.0
        for t in range(i, j):
            m = int(merchant[t])
            rate[t] = (frauds[m] + alpha * prior) / (counts[m] + alpha)
        for t in range(i, j):
            m = int(merchant[t])
            counts[m] += 1.0
            frauds[m] += y[t]
            g_count += 1.0
            g_fraud += y[t]
        i = j
    return rate


def merchant_encoding_audit(built):
    """Measure the frozen-train merchant rate without refitting a model."""
    merchant = built["merchant"]
    y = built["y"].astype(np.float64)
    train = built["train"]
    test = built["test"]
    alpha = fw.MERCHANT_ALPHA
    n_merch = int(merchant.max()) + 1
    counts = np.bincount(merchant[train], minlength=n_merch).astype(np.float64)
    frauds = np.bincount(merchant[train], weights=y[train], minlength=n_merch).astype(np.float64)
    n_train = float(train.sum())
    sum_y = float(y[train].sum())
    global_rate = sum_y / n_train
    full = (frauds + alpha * global_rate) / (counts + alpha)
    assigned = full[merchant]
    if not np.allclose(assigned, built["merchant_rate"]):
        raise SystemExit("Frozen merchant rate does not match add_train_references")
    loo_counts = counts[merchant] - 1.0
    loo_frauds = frauds[merchant] - y
    loo_global = (sum_y - y) / (n_train - 1.0)
    loo = (loo_frauds + alpha * loo_global) / (loo_counts + alpha)
    gap = np.abs(assigned - loo)
    test_merchants = np.unique(merchant[test])
    test_counts = counts[merchant[test]]
    rare = test_counts < 20
    y_test = built["y"][test]
    return {
        "frozen_rate_includes_each_training_rows_own_label": True,
        "frozen_rate_includes_later_training_labels": True,
        "select_labels_included": 0,
        "confirm_labels_included": 0,
        "test_labels_included": 0,
        "same_step_labels_visible_to_step_causal_rate": False,
        "delayed_confirmation_field_present": False,
        "confirmation_assumption": (
            "BankSim has no label-delay field. The frozen feature assumes every "
            "training label is known before step 120. The expanding feature assumes "
            "a label is known at the end of its own step and before the next step. "
            "Same-step labels are not visible under either corrected method."
        ),
        "train_own_label_gap_mean_abs": float(gap[train].mean()),
        "train_fraud_own_label_gap_mean_abs": float(gap[train & (built["y"] == 1)].mean()),
        "train_own_label_gap_max_abs": float(gap[train].max()),
        "test_unseen_merchant_ids": int(np.sum(counts[test_merchants] == 0)),
        "test_rows_unseen_merchant": int(np.sum(test_counts == 0)),
        "test_rows_merchant_train_count_below_20": int(np.sum(rare)),
        "test_fraud_merchant_train_count_below_20": int(np.sum(rare & (y_test == 1))),
        "test_fraud_merchant_train_count_at_least_20": int(np.sum(~rare & (y_test == 1))),
        "top5_train_fraud_share": float(built["train_merchant_fraud_top5_share"]),
        "train_merchants_with_fraud": int(built["train_merchants_with_fraud"]),
        "merchant_id_count": int(n_merch),
    }


def appearance_codes(values, train_mask):
    """Train-appearance integer codes. Unseen values are -1. Not a target encoding."""
    table = {}
    train_mask = np.asarray(train_mask, dtype=bool)
    for value, keep in zip(values, train_mask):
        if keep and value not in table:
            table[value] = len(table)
    out = np.fromiter((table.get(value, -1) for value in values), dtype=np.int32, count=len(values))
    return out, table


def one_hot_drop_first(values, train_mask):
    """Train-appearance one-hot with the first train level removed."""
    _codes, table = appearance_codes(values, train_mask)
    levels = [None] * len(table)
    for name, code in table.items():
        levels[code] = name
    kept = levels[1:]
    index = {name: pos for pos, name in enumerate(kept)}
    out = np.zeros((len(values), len(kept)), dtype=np.float64)
    for row, value in enumerate(values):
        pos = index.get(value)
        if pos is not None:
            out[row, pos] = 1.0
    names = [f"{value}" for value in kept]
    return out, names, levels


def atavci_matrix(raw, train_mask):
    """Original atavci columns after dropping both zip fields.

    Codes are fit on the training prefix only. The original notebook fit them
    on the full frame before a shuffled split. That codebook change is ADAPTED.
    Age and gender stay in this Track B matrix and are excluded from Track A.
    """
    customer, _ = appearance_codes(raw["customer"], train_mask)
    age, _ = appearance_codes(raw["age"], train_mask)
    gender, _ = appearance_codes(raw["gender"], train_mask)
    merchant, _ = appearance_codes(raw["merchant"], train_mask)
    category, _ = appearance_codes(raw["category"], train_mask)
    names = [
        "step", "customer_code", "age_code", "gender_code",
        "merchant_code", "category_code", "amount",
    ]
    matrix = np.column_stack([
        raw["step"].astype(np.float64),
        customer.astype(np.float64),
        age.astype(np.float64),
        gender.astype(np.float64),
        merchant.astype(np.float64),
        category.astype(np.float64),
        raw["amount"],
    ])
    return matrix, names


def past_only_windows(customer, merchant, step, amount):
    """Customer and merchant history that excludes the current row.

    The 24-step window is every earlier row of the same customer whose step is
    at least current_step - 24. This replaces 0xSushmitha's rolling window,
    which included the current row and treated step as an hour.
    """
    n = len(customer)
    time_since = np.zeros(n, dtype=np.float64)
    same_step = np.zeros(n, dtype=np.float64)
    sum24 = np.zeros(n, dtype=np.float64)
    count24 = np.zeros(n, dtype=np.float64)
    sumsq24 = np.zeros(n, dtype=np.float64)
    pair_prior = np.zeros(n, dtype=np.float64)
    cust_prior = np.zeros(n, dtype=np.float64)
    merch_prior = np.zeros(n, dtype=np.float64)
    last_step = {}
    steps_by_c = defaultdict(list)
    amounts_by_c = defaultdict(list)
    window_sum = defaultdict(float)
    window_sumsq = defaultdict(float)
    window_start = defaultdict(int)
    pair_count = defaultdict(int)
    customer_count = defaultdict(int)
    merchant_count = defaultdict(int)
    for i, (c, m, s, a) in enumerate(zip(customer, merchant, step.tolist(), amount.tolist())):
        s = int(s)
        a = float(a)
        if c in last_step:
            time_since[i] = s - last_step[c]
        start = window_start[c]
        steps_c = steps_by_c[c]
        amounts_c = amounts_by_c[c]
        while start < len(steps_c) and steps_c[start] < s - 24:
            old = amounts_c[start]
            window_sum[c] -= old
            window_sumsq[c] -= old * old
            start += 1
        window_start[c] = start
        same = 0
        for pos in range(len(steps_c) - 1, start - 1, -1):
            if steps_c[pos] != s:
                break
            same += 1
        same_step[i] = same
        sum24[i] = window_sum[c]
        count24[i] = len(steps_c) - start
        sumsq24[i] = window_sumsq[c]
        pair_prior[i] = pair_count[(c, m)]
        cust_prior[i] = customer_count[c]
        merch_prior[i] = merchant_count[m]
        last_step[c] = s
        steps_c.append(s)
        amounts_c.append(a)
        window_sum[c] += a
        window_sumsq[c] += a * a
        pair_count[(c, m)] += 1
        customer_count[c] += 1
        merchant_count[m] += 1
    z = np.zeros(n, dtype=np.float64)
    enough = count24 >= 2
    mean = np.zeros(n, dtype=np.float64)
    var = np.zeros(n, dtype=np.float64)
    mean[enough] = sum24[enough] / count24[enough]
    var[enough] = np.maximum(sumsq24[enough] / count24[enough] - mean[enough] ** 2, 0.0)
    std = np.sqrt(var)
    usable = enough & (std > 1e-8)
    z[usable] = (np.asarray(amount, dtype=np.float64)[usable] - mean[usable]) / std[usable]
    return {
        "time_since_last_txn_days": time_since,
        "prior_same_step_count": same_step,
        "prior_24step_amount_sum": sum24,
        "prior_24step_amount_z": z,
        "pair_prior_count": pair_prior,
        "is_first_interaction": (pair_prior == 0).astype(np.float64),
        "customer_prior_count": cust_prior,
        "merchant_prior_count": merch_prior,
    }


def sushmitha_matrix(raw, train_mask):
    """Adapted 0xSushmitha feature set on the chronological frame.

    Included on purpose: integer customer and merchant codes, age, gender, and
    is_night = (step % 24) <= 5. is_night is their hour-of-day artifact, not a
    clock. Zips are omitted because both original zip fields are single-valued.
    Current-row amount is not inside the rolling window.
    """
    history = past_only_windows(raw["customer"], raw["merchant"], raw["step"], raw["amount"])
    customer, _ = appearance_codes(raw["customer"], train_mask)
    merchant, _ = appearance_codes(raw["merchant"], train_mask)
    age_oh, age_names, _ = one_hot_drop_first(raw["age"], train_mask)
    gender_oh, gender_names, _ = one_hot_drop_first(raw["gender"], train_mask)
    category_oh, category_names, _ = one_hot_drop_first(raw["category"], train_mask)
    is_night = ((raw["step"].astype(np.int16) % 24) <= 5).astype(np.float64)
    columns = [
        raw["amount"],
        raw["step"].astype(np.float64),
        customer.astype(np.float64),
        merchant.astype(np.float64),
        history["time_since_last_txn_days"],
        history["prior_same_step_count"],
        history["prior_24step_amount_sum"],
        history["prior_24step_amount_z"],
        history["pair_prior_count"],
        history["is_first_interaction"],
        history["customer_prior_count"],
        history["merchant_prior_count"],
        is_night,
    ]
    names = [
        "amount", "step", "customer_code", "merchant_code",
        "time_since_last_txn_days", "prior_same_step_count",
        "prior_24step_amount_sum", "prior_24step_amount_z",
        "pair_prior_count", "is_first_interaction",
        "customer_prior_count", "merchant_prior_count", "is_night_step_mod_24",
    ]
    names += [f"age_{name}" for name in age_names]
    names += [f"gender_{name}" for name in gender_names]
    names += [f"category_{name}" for name in category_names]
    matrix = np.column_stack(columns + [age_oh, gender_oh, category_oh])
    return matrix, names


def undersample_indices(y, ratio=SUSHMITHA_UNDERsample_RATIO, seed=200):
    """Keep every positive row and sample negatives to positive/negative = ratio.

    The sampler is a NumPy Generator. It is not bit-identical to imblearn.
    """
    y = np.asarray(y)
    rng = np.random.default_rng(seed)
    positive = np.flatnonzero(y == 1)
    negative = np.flatnonzero(y == 0)
    n_negative = min(len(negative), int(round(len(positive) / ratio)))
    chosen = rng.choice(negative, size=n_negative, replace=False)
    index = np.concatenate([positive, chosen])
    rng.shuffle(index)
    return index


def evaluate(y, score, amount, k=ALERT_BUDGET):
    y = np.asarray(y).astype(np.int8)
    score = np.asarray(score, dtype=np.float64)
    amount = np.asarray(amount, dtype=np.float64)
    if not (len(y) == len(score) == len(amount)):
        raise ValueError("y, score, and amount must have the same length")
    if not np.isfinite(score).all():
        raise ValueError("score has a non-finite value")
    pred = fw.topk_pred(score, amount, k)
    out = fw.confusion(y, pred)
    out["average_precision"] = fw.average_precision(y, score)
    from sklearn.metrics import roc_auc_score

    if len(np.unique(y)) > 1 and len(np.unique(score)) > 1:
        out["roc_auc"] = float(roc_auc_score(y, score))
    else:
        out["roc_auc"] = None
    out["review_budget"] = int(min(max(int(k), 0), len(y)))
    out["score_unique_values"] = int(len(np.unique(score)))
    return out


def evaluate_slice(y, score, amount, mask, k=ALERT_BUDGET):
    mask = np.asarray(mask, dtype=bool)
    return evaluate(y[mask], np.asarray(score)[mask], amount[mask], k)


def fingerprint(array):
    values = np.ascontiguousarray(array)
    return hashlib.sha256(values.tobytes()).hexdigest()


def save_prediction(directory, name, built, score, meta):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    mask = built["test"]
    score = np.asarray(score, dtype=np.float64)
    if len(score) != len(built["y"]):
        raise ValueError(f"{name} score length {len(score)} != {len(built['y'])}")
    part = score[mask]
    if not np.isfinite(part).all():
        raise SystemExit(f"{name} has a non-finite test score")
    payload = {
        "score": part,
        "y": built["y"][mask].astype(np.int8),
        "amount": built["amount"][mask],
        "step": built["step"][mask].astype(np.int16),
        "customer": built["customer"][mask].astype(np.int32),
        "merchant": built["merchant"][mask].astype(np.int32),
        "category": built["native"][mask].astype(np.int16),
    }
    np.savez_compressed(directory / f"{name}.npz", **payload)
    body = {
        "model": name,
        **meta,
        "test": evaluate(payload["y"], payload["score"], payload["amount"]),
        "test_rows": int(mask.sum()),
        "test_fraud": int(built["y"][mask].sum()),
        "fingerprints": {
            key: fingerprint(payload[key]) for key in payload if key != "score"
        },
    }
    if np.isfinite(score[built["select"]]).all():
        body["select"] = evaluate_slice(built["y"], score, built["amount"], built["select"])
    if np.isfinite(score[built["confirm"]]).all():
        body["confirm"] = evaluate_slice(built["y"], score, built["amount"], built["confirm"])
    text = json.dumps(body, indent=2, sort_keys=True, default=_json_default) + "\n"
    (directory / f"{name}.json").write_text(text)
    return body


def _json_default(value):
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value).__name__)


def topk_labels(score, amount, k=ALERT_BUDGET):
    return fw.topk_pred(np.asarray(score, dtype=np.float64), np.asarray(amount, dtype=np.float64), k)


def amount_slice_table(y, pred, amount):
    y = np.asarray(y).astype(bool)
    pred = np.asarray(pred).astype(bool)
    amount = np.asarray(amount, dtype=np.float64)
    rows = []
    for name, low, high in AMOUNT_SLICES:
        mask = amount >= low if high is None else (amount >= low) & (amount < high)
        fraud = mask & y
        rows.append({
            "slice": name,
            "rows": int(mask.sum()),
            "fraud": int(fraud.sum()),
            "detected_fraud": int(np.sum(fraud & pred)),
            "missed_fraud": int(np.sum(fraud & ~pred)),
            "false_positives": int(np.sum(mask & pred & ~y)),
        })
    return rows


def category_breakdown(y, pred, codes, names):
    return fw.category_table(y, pred, codes, names)


def _block_groups(codes):
    groups = {}
    for index, code in enumerate(np.asarray(codes).tolist()):
        groups.setdefault(int(code), []).append(index)
    keys = np.array(sorted(groups), dtype=np.int64)
    arrays = {key: np.asarray(value, dtype=np.int32) for key, value in groups.items()}
    return keys, arrays


def paired_block_bootstrap(
    y, amount, block, score_a, score_b,
    n_boot=N_BOOT, seed=BOOT_SEED, budget_rate=BUDGET_RATE,
):
    """Paired bootstrap. Difference is model A minus model B.

    Rows of a drawn block are included once per draw, including duplicates.
    The alert count scales with the resampled population at budget_rate.
    """
    y = np.asarray(y).astype(np.int8)
    amount = np.asarray(amount, dtype=np.float64)
    score_a = np.asarray(score_a, dtype=np.float64)
    score_b = np.asarray(score_b, dtype=np.float64)
    keys, groups = _block_groups(block)
    rng = np.random.default_rng(seed)
    d_ap = np.empty(n_boot, dtype=np.float64)
    d_tp = np.empty(n_boot, dtype=np.float64)
    for draw in range(n_boot):
        chosen = rng.choice(keys, size=len(keys), replace=True)
        index = np.concatenate([groups[int(key)] for key in chosen])
        k = min(max(int(round(budget_rate * len(index))), 0), len(index))
        d_ap[draw] = fw.average_precision(y[index], score_a[index]) - fw.average_precision(
            y[index], score_b[index],
        )
        pred_a = fw.topk_pred(score_a[index], amount[index], k)
        pred_b = fw.topk_pred(score_b[index], amount[index], k)
        d_tp[draw] = np.sum(pred_a & (y[index] == 1)) - np.sum(pred_b & (y[index] == 1))

    def pack(diff):
        low, high = np.quantile(diff, [0.025, 0.975])
        return {
            "mean": float(diff.mean()),
            "ci95_low": float(low),
            "ci95_high": float(high),
            "includes_zero": bool(low <= 0.0 <= high),
            "n_boot": int(n_boot),
            "seed": int(seed),
        }

    return {
        "difference": "A_minus_B",
        "block_count": int(len(keys)),
        "budget_rate": float(budget_rate),
        "ap": pack(d_ap),
        "tp_at_scaled_budget": pack(d_tp),
    }


def compare_reported(name, metrics):
    reported = PREVIOUSLY_REPORTED["models"].get(name)
    if reported is None:
        return None
    return {
        "reported_average_precision": reported["average_precision"],
        "measured_average_precision": metrics["average_precision"],
        "ap_abs_diff": abs(metrics["average_precision"] - reported["average_precision"]),
        "tp_match": metrics["TP"] == reported["TP"],
        "fp_match": metrics["FP"] == reported["FP"],
        "fn_match": metrics["FN"] == reported["FN"],
        "tn_match": metrics["TN"] == reported["TN"],
    }


def self_check():
    fw.self_check()
    y = np.array([1, 0, 1, 0])
    score = np.array([0.2, 0.9, 0.4, 0.1])
    amount = np.array([5.0, 1.0, 9.0, 3.0])
    metrics = evaluate(y, score, amount, k=2)
    assert metrics["alerts"] == 2
    assert metrics["TP"] + metrics["FP"] + metrics["TN"] + metrics["FN"] == 4
    merchant = np.array([0, 0, 0, 1])
    labels = np.array([1, 0, 1, 0])
    step = np.array([0, 0, 1, 2])
    train = np.array([True, True, True, False])
    causal = step_causal_merchant_rate(merchant, labels, step, train)
    assert causal[0] == 0.0 and causal[1] == 0.0
    assert abs(causal[2] - (11.0 / 22.0)) < 1e-12
    assert abs(causal[3] - (2.0 / 3.0)) < 1e-12
    expanding = expanding_merchant_rate(
        np.array([0, 0, 0]), np.array([1, 0, 0]), np.array([0, 1, 2]),
    )
    assert expanding[0] == 0.0
    assert abs(expanding[2] - ((1.0 + 20.0 * 0.5) / 22.0)) < 1e-12
    customers = ["A", "A", "A", "A"]
    merchants = ["M", "M", "N", "M"]
    windows = past_only_windows(
        customers, merchants, np.array([0, 0, 1, 26]), np.array([10.0, 30.0, 10.0, 5.0]),
    )
    assert windows["prior_same_step_count"].tolist() == [0, 1, 0, 0]
    assert windows["customer_prior_count"].tolist() == [0, 1, 2, 3]
    assert windows["pair_prior_count"].tolist() == [0, 1, 0, 2]
    assert windows["is_first_interaction"].tolist() == [1, 0, 1, 0]
    assert abs(windows["prior_24step_amount_sum"][2] - 40.0) < 1e-9
    assert abs(windows["prior_24step_amount_z"][2] + 1.0) < 1e-9
    assert windows["prior_24step_amount_sum"][3] == 0.0
    codes, _ = appearance_codes(["b", "a", "c"], np.array([True, True, False]))
    assert codes.tolist() == [0, 1, -1]
    hot, names, _ = one_hot_drop_first(["a", "b", "a"], np.array([True, True, True]))
    assert names == ["b"]
    assert hot[:, 0].tolist() == [0.0, 1.0, 0.0]
    index = undersample_indices(np.array([1, 0, 0, 0, 0, 1]), ratio=0.5, seed=1)
    assert set(np.where(np.array([1, 0, 0, 0, 0, 1]) == 1)[0]).issubset(set(index.tolist()))
    boot = paired_block_bootstrap(
        np.array([1, 0, 1, 0]),
        np.array([1.0, 2.0, 3.0, 4.0]),
        np.array([7, 7, 8, 8]),
        np.array([0.9, 0.1, 0.8, 0.2]),
        np.array([0.2, 0.8, 0.1, 0.7]),
        n_boot=8,
        seed=1,
        budget_rate=0.5,
    )
    assert boot["block_count"] == 2
    assert "includes_zero" in boot["ap"]


if __name__ == "__main__":
    self_check()
    print("contract self_check ok")
