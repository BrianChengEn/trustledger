"""Independent auditor for BankSim prediction npz files.

This script does not train a model, does not read backend/.env, and does not
treat steps 150-179 as an untouched holdout. Bootstrap means are reported
only as uncertainty; the leaderboard key is the full-test Average Precision.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

import contract  # noqa: E402

AUDIT_DIR = Path(__file__).resolve().parent
AUDIT_TXT = AUDIT_DIR / "AUDIT.txt"
AUDIT_JSON = AUDIT_DIR / "audit_report.json"
SELF_CHECK_TXT = AUDIT_DIR / "SELF_CHECK.txt"
SYNTH_ROOT = Path("/tmp/tl-audit-selfcheck")

EXPECTED_ROWS = 111_306
EXPECTED_FRAUD = 1_200
ALERT_BUDGET = 919
SIMILAR_AP = 0.01
METRIC_ATOL = 1e-8
ALIGN_FIELDS = ("y", "amount", "step", "customer", "merchant", "category")
REQUIRED_FIELDS = ("score",) + ALIGN_FIELDS

HOLDOUT_STATEMENT = (
    "steps 150–179 已經在 PR #14 與 PR #15 看過。"
    "這次是可重現的對照實驗，不是未被看過的盲測。"
)
RANKING_RULE = (
    "榜單只按完整 test 的 Average Precision 點估計排序。"
    "Bootstrap 的平均數不是排序鍵，也不用來重排榜單。"
)

_TRACK_A_RE = re.compile(r"(?<![a-z0-9])track\s*[-_ ]?a\b", re.IGNORECASE)
_MERCHANT_RATE_RE = re.compile(
    r"merchant[_\s-]*fraud[_\s-]*rate|merchant[_\s-]*rate",
    re.IGNORECASE,
)
_MERCHANT_EXCLUSION_RE = re.compile(
    r"no merchant|without merchant|excluded merchant|exclude merchant|"
    r"not use merchant|沒有\s*merchant|不含\s*merchant|排除\s*merchant|"
    r"沒有商家詐欺率|不含商家詐欺率",
    re.IGNORECASE,
)
_HOLDOUT_PHRASES = (
    "untouched holdout",
    "pristine blind",
    "pristine holdout",
    "blind holdout",
    "blind test",
    "unseen holdout",
    "unseen test",
    "never-before-seen",
    "not previously inspected",
    "independent blind",
    "未被看過的盲測",
    "未被看過的 holdout",
    "未接觸的 holdout",
    "未接觸的盲測",
    "獨立、未接觸的 holdout",
    "獨立盲測",
)
_NEGATION_MARKERS = (
    "not ",
    "no ",
    "never ",
    "不是",
    "並非",
    "不可",
    "不能",
    "不要",
)


def independent_topk_mask(score, amount, k):
    """Higher score, then higher amount, then smaller row index."""
    score = np.asarray(score, dtype=np.float64)
    amount = np.asarray(amount, dtype=np.float64)
    k_use = min(max(int(k), 0), len(score))
    order = np.lexsort((np.arange(len(score), dtype=np.int64), -amount, -score))
    pred = np.zeros(len(score), dtype=bool)
    if k_use:
        pred[order[:k_use]] = True
    return pred


def _divide(num, den):
    if den == 0:
        return None
    return num / den


def independent_average_precision(y, score):
    y = np.asarray(y)
    if int(np.sum(y, dtype=np.int64)) == 0:
        return 0.0
    return float(average_precision_score(y, np.asarray(score, dtype=np.float64)))


def independent_roc_auc(y, score):
    y = np.asarray(y)
    score = np.asarray(score, dtype=np.float64)
    # One class is undefined. A constant score still goes through sklearn,
    # which returns 0.5; the contract returns null and the difference is flagged.
    if len(np.unique(y)) < 2:
        return None
    return float(roc_auc_score(y, score))


def independent_evaluate(y, score, amount, k=ALERT_BUDGET):
    """TP/FP/TN/FN from this file's own top-k mask, plus sklearn AP and ROC AUC."""
    y = np.asarray(y)
    score = np.asarray(score, dtype=np.float64)
    amount = np.asarray(amount, dtype=np.float64)
    if not (len(y) == len(score) == len(amount)):
        raise ValueError("y, score, and amount must have the same length")
    pred = independent_topk_mask(score, amount, k)
    truth = y.astype(bool)
    tp = int(np.count_nonzero(pred & truth))
    fp = int(np.count_nonzero(pred & ~truth))
    tn = int(np.count_nonzero(~pred & ~truth))
    fn = int(np.count_nonzero(~pred & truth))
    precision = _divide(tp, tp + fp)
    recall = _divide(tp, tp + fn)
    specificity = _divide(tn, tn + fp)
    f1 = None
    if precision is not None and recall is not None and precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    balanced = None
    if recall is not None and specificity is not None:
        balanced = 0.5 * (recall + specificity)
    return {
        "TP": tp,
        "FP": fp,
        "TN": tn,
        "FN": fn,
        "n": tp + fp + tn + fn,
        "alerts": tp + fp,
        "accuracy": _divide(tp + tn, tp + fp + tn + fn),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "fpr": _divide(fp, fp + tn),
        "balanced_accuracy": balanced,
        "average_precision": independent_average_precision(y, score),
        "roc_auc": independent_roc_auc(y, score),
        "review_budget": int(min(max(int(k), 0), len(y))),
        "score_unique_values": int(len(np.unique(score))),
    }


def metric_differences(contract_metrics, independent_metrics):
    diffs = {}
    keys = [
        "TP", "FP", "TN", "FN", "n", "alerts",
        "accuracy", "precision", "recall", "f1", "fpr", "balanced_accuracy",
        "average_precision", "roc_auc", "review_budget", "score_unique_values",
    ]
    for key in keys:
        left = _plain_number(contract_metrics.get(key))
        right = _plain_number(independent_metrics.get(key))
        if left is None and right is None:
            continue
        if left is None or right is None:
            diffs[key] = {"contract": left, "independent": right, "abs_diff": None}
            continue
        if isinstance(left, int) and isinstance(right, int):
            if left != right:
                diffs[key] = {
                    "contract": left,
                    "independent": right,
                    "abs_diff": abs(left - right),
                }
            continue
        delta = abs(float(left) - float(right))
        if delta > METRIC_ATOL:
            diffs[key] = {
                "contract": float(left),
                "independent": float(right),
                "abs_diff": delta,
            }
    return diffs


def _plain_number(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value)
    return value


def plain(value):
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def same_array(left, right):
    if left.shape != right.shape or left.dtype != right.dtype:
        return False
    return np.ascontiguousarray(left).tobytes() == np.ascontiguousarray(right).tobytes()


def hand_step_causal_toy():
    """merchant [0,0,0,1], y [1,0,1,0], step [0,0,1,2], train prefix length 3.

    Alpha is fixed at 20. Same-step labels stay invisible. The row after the
    train prefix uses the frozen train aggregate, not its own label.
    """
    alpha = 20.0
    row0 = (0.0 + alpha * 0.0) / (0.0 + alpha)
    row1 = (0.0 + alpha * 0.0) / (0.0 + alpha)
    earlier_merchant_fraud = 1.0
    earlier_merchant_count = 2.0
    earlier_global_fraud = 1.0
    earlier_global_count = 2.0
    prior = earlier_global_fraud / earlier_global_count
    row2 = (earlier_merchant_fraud + alpha * prior) / (earlier_merchant_count + alpha)
    train_fraud = 1.0 + 0.0 + 1.0
    train_rows = 3.0
    unseen_fraud = 0.0
    unseen_count = 0.0
    row3 = (unseen_fraud + alpha * (train_fraud / train_rows)) / (unseen_count + alpha)
    return np.array([row0, row1, row2, row3], dtype=np.float64)


def identical_score_arrays(score_a, score_b, sidecar_a, sidecar_b):
    """Fire only when both JSON sidecars exist and the score bytes match."""
    if sidecar_a is None or sidecar_b is None:
        return None
    score_a = np.asarray(score_a)
    score_b = np.asarray(score_b)
    if score_a.shape != score_b.shape or score_a.dtype != score_b.dtype:
        return None
    if not same_array(score_a, score_b):
        return None
    return {
        "code": "identical_scores",
        "detail": "兩個模型的 score 陣列完全相同，可能是複製而不是獨立訓練。",
    }


def _collect_average_precisions(obj, path=""):
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{path}.{key}" if path else key
            if key == "average_precision" and isinstance(value, (int, float)) and not isinstance(value, bool):
                found.append((child, float(value)))
            else:
                found.extend(_collect_average_precisions(value, child))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(_collect_average_precisions(value, f"{path}[{index}]"))
    return found


def ap_above_0_999(sidecar, measured=None):
    if not isinstance(sidecar, dict):
        return None
    hits = []
    if measured is not None and float(measured) > 0.999:
        hits.append({"path": "measured_test", "average_precision": float(measured)})
    for path, value in _collect_average_precisions(sidecar):
        if value > 0.999:
            hits.append({"path": path, "average_precision": value})
    if not hits:
        return None
    return {
        "code": "ap_above_0_999",
        "detail": "Average Precision 高於 0.999。在這份已看過的 test 上，這不是可信的未調整結果。",
        "hits": hits,
    }


def _has_present_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            value = obj[key]
            if value not in (None, "", [], {}):
                return True
        return any(_has_present_key(value, key) for value in obj.values())
    if isinstance(obj, list):
        return any(_has_present_key(value, key) for value in obj)
    return False


def missing_leakage_status(sidecar):
    if not isinstance(sidecar, dict):
        return None
    if _has_present_key(sidecar, "leakage_status"):
        return None
    return {
        "code": "missing_leakage_status",
        "detail": "JSON sidecar 沒有 leakage_status，無法判斷特徵是否含有訓練標籤。",
    }


def _first_number(mapping, key):
    if not isinstance(mapping, dict) or key not in mapping:
        return None
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def test_length_drift(sidecar, observed_rows=None, observed_fraud=None):
    if not isinstance(sidecar, dict):
        return None
    problems = []
    rows = _first_number(sidecar, "test_rows")
    fraud = _first_number(sidecar, "test_fraud")
    test = sidecar.get("test")
    test_n = _first_number(test, "n") if isinstance(test, dict) else None
    if rows is not None and rows != EXPECTED_ROWS:
        problems.append({"field": "test_rows", "value": rows, "expected": EXPECTED_ROWS})
    if fraud is not None and fraud != EXPECTED_FRAUD:
        problems.append({"field": "test_fraud", "value": fraud, "expected": EXPECTED_FRAUD})
    if test_n is not None and test_n != EXPECTED_ROWS:
        problems.append({"field": "test.n", "value": test_n, "expected": EXPECTED_ROWS})
    if rows is not None and observed_rows is not None and rows != int(observed_rows):
        problems.append({"field": "test_rows_vs_npz", "json": rows, "npz": int(observed_rows)})
    if fraud is not None and observed_fraud is not None and fraud != int(observed_fraud):
        problems.append({
            "field": "test_fraud_vs_npz",
            "json": fraud,
            "npz": int(observed_fraud),
        })
    if not problems:
        return None
    return {
        "code": "test_length_drift",
        "detail": "JSON 記載的 test 長度或詐欺數和凍結的 BankSim test 不一致。",
        "problems": problems,
    }


def _is_track_a(value):
    text = str(value).strip().lower()
    if text in {"a", "track a", "track_a", "track-a"}:
        return True
    return _TRACK_A_RE.search(text) is not None


def _is_merchant_rate_name(value):
    return _MERCHANT_RATE_RE.search(str(value)) is not None


def _walk_track_values(obj):
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in {"track", "feature_track", "track_name"} and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_walk_track_values(value))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(_walk_track_values(value))
    return found


def _walk_feature_names(obj):
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in {"features", "feature_names", "columns", "feature_columns"} and isinstance(value, list):
                found.extend(str(item) for item in value)
            else:
                found.extend(_walk_feature_names(value))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(_walk_feature_names(value))
    return found


def _walk_strings(obj):
    found = []
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            found.extend(_walk_strings(value))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(_walk_strings(value))
    return found


def merchant_rate_as_track_a(sidecar):
    if not isinstance(sidecar, dict):
        return None
    tracks = [value for value in _walk_track_values(sidecar) if _is_track_a(value)]
    feature_hits = [name for name in _walk_feature_names(sidecar) if _is_merchant_rate_name(name)]
    if tracks and feature_hits:
        return {
            "code": "track_a_merchant_rate",
            "detail": "Track A 不能包含 merchant fraud rate。這份 sidecar 把 merchant rate 放進 Track A。",
            "track": tracks,
            "features": feature_hits,
        }
    prose_hits = []
    for text in _walk_strings(sidecar):
        if not _is_track_a(text) or not _is_merchant_rate_name(text):
            continue
        if _MERCHANT_EXCLUSION_RE.search(text):
            continue
        prose_hits.append(text)
    if not prose_hits:
        return None
    return {
        "code": "track_a_merchant_rate",
        "detail": "文字把 merchant rate 描述成 Track A 特徵。Track A 沒有 merchant fraud rate。",
        "prose": prose_hits,
    }


def _negated_at(text, start):
    window = text[max(0, start - 24):start].lower()
    return any(marker in window for marker in _NEGATION_MARKERS)


def untouched_holdout_claim(sidecar):
    if not isinstance(sidecar, dict):
        return None
    hits = []
    for text in _walk_strings(sidecar):
        lowered = text.lower()
        for phrase in _HOLDOUT_PHRASES:
            begin = 0
            needle = phrase.lower()
            while True:
                found = lowered.find(needle, begin)
                if found < 0:
                    break
                if not _negated_at(lowered, found):
                    hits.append({"phrase": phrase, "text": text})
                    break
                begin = found + len(needle)
    if not hits:
        return None
    return {
        "code": "untouched_holdout_claim",
        "detail": "sidecar 宣稱未被看過的 holdout。steps 150–179 已經被 PR #14 與 PR #15 看過。",
        "hits": hits,
    }


def _loaded_score(item):
    arrays = item.get("arrays") or {}
    score = arrays.get("score")
    if score is None:
        return None
    return np.asarray(score)


def collect_suspicions(loaded):
    findings = []
    names = list(loaded)
    for left, right in combinations(names, 2):
        score_a = _loaded_score(loaded[left])
        score_b = _loaded_score(loaded[right])
        if score_a is None or score_b is None:
            continue
        found = identical_score_arrays(
            score_a,
            score_b,
            loaded[left]["sidecar"],
            loaded[right]["sidecar"],
        )
        if found is not None:
            findings.append({**found, "model_a": left, "model_b": right})
    for name, item in loaded.items():
        measured = item.get("measured_ap")
        observed_rows = item.get("rows")
        observed_fraud = item.get("fraud")
        checks = (
            ap_above_0_999(item["sidecar"], measured=measured),
            missing_leakage_status(item["sidecar"]),
            test_length_drift(
                item["sidecar"],
                observed_rows=observed_rows,
                observed_fraud=observed_fraud,
            ),
            merchant_rate_as_track_a(item["sidecar"]),
            untouched_holdout_claim(item["sidecar"]),
        )
        for found in checks:
            if found is not None:
                findings.append({**found, "model": name})
    return findings


def sidecar_notes(loaded):
    missing = [name for name, item in loaded.items() if item["sidecar"] is None]
    if not missing:
        return []
    return [{
        "level": "info",
        "code": "no_json_sidecar",
        "models": missing,
        "detail": "這些模型沒有 JSON sidecar。相同分數、完美 AP、缺 leakage_status 等檢查不會觸發。",
    }]


def load_sidecar(path: Path):
    sidecar_path = path.with_suffix(".json")
    if not sidecar_path.exists():
        return None
    return json.loads(sidecar_path.read_text(encoding="utf-8"))


def load_prediction(path: Path):
    with np.load(path, allow_pickle=False) as handle:
        keys = set(handle.files)
        missing = [key for key in REQUIRED_FIELDS if key not in keys]
        if missing:
            return {"path": str(path), "missing": missing}
        payload = {key: np.asarray(handle[key]) for key in REQUIRED_FIELDS}
    return {"path": str(path), "arrays": payload, "missing": []}


def _failure(code, **extra):
    body = {"code": code}
    body.update(extra)
    return body


def audit_loaded(loaded, expect_banks, budget):
    """Audit already-loaded prediction arrays. `loaded` maps name to a record."""
    failures = []
    models = []
    reference_name = None
    reference = None
    for name in sorted(loaded):
        item = loaded[name]
        arrays = item["arrays"]
        if item.get("missing"):
            failures.append(_failure("missing_array", model=name, fields=item["missing"]))
            continue
        score = np.asarray(arrays["score"], dtype=np.float64)
        y = arrays["y"]
        amount = arrays["amount"]
        rows = int(len(score))
        fraud = int(np.sum(y, dtype=np.int64))
        item["rows"] = rows
        item["fraud"] = fraud
        if any(len(arrays[field]) != rows for field in ALIGN_FIELDS):
            failures.append(_failure("length", model=name, detail="欄位長度不一致"))
        if expect_banks and rows != EXPECTED_ROWS:
            failures.append(_failure(
                "length", model=name, rows=rows, expected=EXPECTED_ROWS,
            ))
        if expect_banks and fraud != EXPECTED_FRAUD:
            failures.append(_failure(
                "fraud_count", model=name, fraud=fraud, expected=EXPECTED_FRAUD,
            ))
        fingerprints = {
            field: contract.fingerprint(arrays[field]) for field in ALIGN_FIELDS
        }
        if reference is None:
            reference_name = name
            reference = arrays
        else:
            for field in ALIGN_FIELDS:
                if not same_array(arrays[field], reference[field]):
                    failures.append(_failure(
                        "alignment",
                        model=name,
                        reference=reference_name,
                        field=field,
                    ))
                if fingerprints[field] != contract.fingerprint(reference[field]):
                    failures.append(_failure(
                        "fingerprint",
                        model=name,
                        reference=reference_name,
                        field=field,
                    ))
        if not np.isfinite(score).all():
            failures.append(_failure("non_finite_score", model=name))
            models.append({
                "model": name,
                "rows": rows,
                "fraud": fraud,
                "finite_score": False,
                "fingerprints": fingerprints,
            })
            continue
        contract_mask = np.asarray(contract.topk_labels(score, amount, budget)).astype(bool)
        own_mask = independent_topk_mask(score, amount, budget)
        alerts = int(contract_mask.sum())
        if alerts != int(budget):
            failures.append(_failure(
                "alert_budget",
                model=name,
                alerts=alerts,
                requested_budget=int(budget),
            ))
        if contract_mask.shape != own_mask.shape or not np.array_equal(contract_mask, own_mask):
            failures.append(_failure("topk_disagreement", model=name))
        contract_metrics = plain(contract.evaluate(y, score, amount, k=budget))
        own_metrics = independent_evaluate(y, score, amount, k=budget)
        diffs = metric_differences(contract_metrics, own_metrics)
        if diffs:
            failures.append(_failure("metric_mismatch", model=name, differences=diffs))
        item["measured_ap"] = own_metrics["average_precision"]
        record = {
            "model": name,
            "path": item["path"],
            "rows": rows,
            "fraud": fraud,
            "finite_score": True,
            "alerts": alerts,
            "contract_metrics": contract_metrics,
            "independent_metrics": own_metrics,
            "metric_differences": diffs,
            "fingerprints": fingerprints,
            "previously_reported": plain(contract.compare_reported(name, contract_metrics)),
        }
        models.append(record)
    shared = None
    if reference is not None and not any(item["code"] == "alignment" for item in failures):
        shared = {
            field: contract.fingerprint(reference[field]) for field in ALIGN_FIELDS
        }
    suspicions = collect_suspicions(loaded)
    notes = sidecar_notes(loaded)
    ranked_models = [
        row for row in models
        if row.get("finite_score") and not _model_ranking_block(row["model"], failures)
    ]
    blocked = _shared_ranking_block(failures) or not ranked_models
    leaderboard = None if blocked else rank_models(ranked_models)
    close_pairs = [] if leaderboard is None else close_ap_pairs(leaderboard, SIMILAR_AP)
    integrity_ok = not failures
    return {
        "role": "independent BankSim metric audit",
        "holdout_statement": HOLDOUT_STATEMENT,
        "ranking_rule": RANKING_RULE,
        "expect_banks": bool(expect_banks),
        "budget": int(budget),
        "model_count": len(loaded),
        "integrity_ok": integrity_ok,
        "suspicions": suspicions,
        "notes": notes,
        "failures": failures,
        "ok": integrity_ok and not suspicions,
        "shared_fingerprints": shared,
        "models": models,
        "leaderboard_blocked": blocked,
        "leaderboard": leaderboard,
        "close_pairs": close_pairs,
        "bootstrap": None,
        "overlap": None,
        "amount_slices": None,
    }


def _shared_ranking_block(failures):
    """Label or population disagreements make every rank incomparable."""
    blocking = {
        "alignment",
        "fingerprint",
        "length",
        "fraud_count",
        "no_predictions",
    }
    return any(item["code"] in blocking for item in failures)


def _model_ranking_block(name, failures):
    blocking = {"non_finite_score", "alert_budget", "topk_disagreement", "metric_mismatch"}
    return any(item.get("model") == name and item["code"] in blocking for item in failures)


def rank_models(models):
    """Sort by full-test Average Precision only. Bootstrap means are not an input."""
    ordered = sorted(
        models,
        key=lambda row: (-float(row["independent_metrics"]["average_precision"]), row["model"]),
    )
    board = []
    for rank, row in enumerate(ordered, start=1):
        metrics = row["independent_metrics"]
        board.append({
            "rank": rank,
            "model": row["model"],
            "average_precision": metrics["average_precision"],
            "roc_auc": metrics["roc_auc"],
            "TP": metrics["TP"],
            "FP": metrics["FP"],
            "TN": metrics["TN"],
            "FN": metrics["FN"],
            "alerts": metrics["alerts"],
            "score_unique_values": metrics["score_unique_values"],
            "ranking_key": "full_test_average_precision",
        })
    return board


def close_ap_pairs(leaderboard, tolerance=SIMILAR_AP):
    pairs = []
    for left, right in combinations(leaderboard, 2):
        gap = abs(left["average_precision"] - right["average_precision"])
        if gap <= tolerance:
            pairs.append({
                "model_a": left["model"],
                "model_b": right["model"],
                "abs_ap_gap": gap,
                "note": "AP 差距在 0.01 以內，先視為接近。點估計順序保持不變。",
            })
    return pairs


def fraud_overlap(y, pred_a, pred_b):
    fraud = np.asarray(y).astype(bool)
    pred_a = np.asarray(pred_a).astype(bool)
    pred_b = np.asarray(pred_b).astype(bool)
    both = int(np.count_nonzero(fraud & pred_a & pred_b))
    only_a = int(np.count_nonzero(fraud & pred_a & ~pred_b))
    only_b = int(np.count_nonzero(fraud & ~pred_a & pred_b))
    neither = int(np.count_nonzero(fraud & ~pred_a & ~pred_b))
    return {
        "both": both,
        "only_a": only_a,
        "only_b": only_b,
        "neither": neither,
        "fraud": both + only_a + only_b + neither,
    }


def point_estimates(metrics):
    return {
        "average_precision": metrics["average_precision"],
        "roc_auc": metrics["roc_auc"],
        "TP": metrics["TP"],
        "FP": metrics["FP"],
        "TN": metrics["TN"],
        "FN": metrics["FN"],
        "alerts": metrics["alerts"],
        "source": "full_test_point_estimate",
    }


def add_overlap(report, loaded, budget):
    if report["leaderboard_blocked"]:
        report["overlap"] = {
            "skipped": True,
            "reason": "完整性檢查失敗，不計算詐欺重疊。",
        }
        report["amount_slices"] = {
            "skipped": True,
            "reason": "完整性檢查失敗，不計算金額切片。",
        }
        return report
    ready = []
    for name in sorted(loaded):
        item = loaded[name]
        if item.get("missing") or "measured_ap" not in item:
            continue
        score = np.asarray(item["arrays"]["score"], dtype=np.float64)
        amount = item["arrays"]["amount"]
        pred = np.asarray(contract.topk_labels(score, amount, budget)).astype(bool)
        ready.append((name, item, pred))
    slices = {}
    for name, item, pred in ready:
        slices[name] = contract.amount_slice_table(item["arrays"]["y"], pred, item["arrays"]["amount"])
    pairs = []
    for (name_a, item_a, pred_a), (name_b, item_b, pred_b) in combinations(ready, 2):
        if not same_array(item_a["arrays"]["y"], item_b["arrays"]["y"]):
            continue
        counts = fraud_overlap(item_a["arrays"]["y"], pred_a, pred_b)
        pairs.append({
            "model_a": name_a,
            "model_b": name_b,
            "budget": int(budget),
            **counts,
        })
    report["overlap"] = pairs
    report["amount_slices"] = plain(slices)
    return report


def add_bootstrap(report, loaded, name_a, name_b, block_name, budget, n_boot=None, seed=None):
    if name_a not in loaded or name_b not in loaded:
        missing = [name for name in (name_a, name_b) if name not in loaded]
        report["failures"].append(_failure("missing_model", models=missing))
        report["integrity_ok"] = False
        report["ok"] = False
        report["bootstrap"] = {"skipped": True, "reason": "找不到 --pair 指定的模型。"}
        return report
    if report["leaderboard_blocked"]:
        report["bootstrap"] = {
            "skipped": True,
            "reason": "完整性檢查失敗，不跑 paired bootstrap。",
        }
        return report
    left = loaded[name_a]
    right = loaded[name_b]
    if not same_array(left["arrays"]["y"], right["arrays"]["y"]):
        report["bootstrap"] = {"skipped": True, "reason": "兩份 y 不一致。"}
        return report
    if block_name not in left["arrays"]:
        report["failures"].append(_failure("missing_array", model=name_a, fields=[block_name]))
        report["integrity_ok"] = False
        report["ok"] = False
        return report
    if not np.isfinite(left["arrays"]["score"]).all() or not np.isfinite(right["arrays"]["score"]).all():
        report["bootstrap"] = {"skipped": True, "reason": "score 含有非有限值。"}
        return report
    kwargs = {}
    if n_boot is not None:
        kwargs["n_boot"] = int(n_boot)
    if seed is not None:
        kwargs["seed"] = int(seed)
    block = left["arrays"][block_name]
    result = contract.paired_block_bootstrap(
        left["arrays"]["y"],
        left["arrays"]["amount"],
        block,
        left["arrays"]["score"],
        right["arrays"]["score"],
        **kwargs,
    )
    unique_blocks = int(len(np.unique(block)))
    if int(result["block_count"]) != unique_blocks:
        report["failures"].append(_failure(
            "block_count",
            reported=int(result["block_count"]),
            unique=unique_blocks,
        ))
        report["integrity_ok"] = False
        report["ok"] = False
    metrics = {row["model"]: row for row in report["models"]}
    report["bootstrap"] = {
        "model_a": name_a,
        "model_b": name_b,
        "block": block_name,
        "difference": result["difference"],
        "block_count": int(result["block_count"]),
        "budget_rate": float(result["budget_rate"]),
        "ap": plain(result["ap"]),
        "tp_at_scaled_budget": plain(result["tp_at_scaled_budget"]),
        "includes_zero_ap": bool(result["ap"]["includes_zero"]),
        "includes_zero_tp": bool(result["tp_at_scaled_budget"]["includes_zero"]),
        "full_test_point_estimates": {
            name_a: point_estimates(metrics[name_a]["independent_metrics"]),
            name_b: point_estimates(metrics[name_b]["independent_metrics"]),
        },
        "ranking_note": "bootstrap 平均數沒有用來重排榜單。區間含 0 就不宣稱兩者有清楚差異。",
        "requested_budget": int(budget),
    }
    return report


def audit_directory(directory, expect_banks, budget, pair=None, block=None, overlap=False, n_boot=None, seed=None):
    directory = Path(directory)
    report_base = {
        "role": "independent BankSim metric audit",
        "holdout_statement": HOLDOUT_STATEMENT,
        "ranking_rule": RANKING_RULE,
        "score_dir": str(directory),
        "expect_banks": bool(expect_banks),
        "budget": int(budget),
        "model_count": 0,
        "integrity_ok": False,
        "ok": False,
        "failures": [],
        "suspicions": [],
        "notes": [],
        "shared_fingerprints": None,
        "models": [],
        "leaderboard_blocked": True,
        "leaderboard": None,
        "close_pairs": [],
        "bootstrap": None,
        "overlap": None,
        "amount_slices": None,
    }
    if not directory.exists() or not directory.is_dir():
        report_base["failures"].append(_failure(
            "no_predictions",
            detail=f"分數目錄不存在：{directory}",
        ))
        return report_base
    paths = sorted(directory.glob("*.npz"))
    if not paths:
        report_base["failures"].append(_failure(
            "no_predictions",
            detail=f"{directory} 裡沒有 *.npz，沒有編造榜單。",
        ))
        return report_base
    loaded = {}
    failures = []
    for path in paths:
        try:
            parsed = load_prediction(path)
        except Exception as exc:
            failures.append(_failure("unreadable", model=path.stem, detail=str(exc)))
            continue
        sidecar = None
        if not parsed.get("missing"):
            try:
                sidecar = load_sidecar(path)
            except Exception as exc:
                failures.append(_failure("unreadable_sidecar", model=path.stem, detail=str(exc)))
        loaded[path.stem] = {
            "path": parsed["path"],
            "arrays": parsed.get("arrays", {}),
            "missing": parsed.get("missing", []),
            "sidecar": sidecar,
        }
    if not loaded and failures:
        report_base["failures"] = failures
        return report_base
    report = audit_loaded(loaded, expect_banks=expect_banks, budget=budget)
    report["score_dir"] = str(directory)
    report["failures"] = failures + report["failures"]
    report["integrity_ok"] = not report["failures"]
    report["leaderboard_blocked"] = _shared_ranking_block(report["failures"]) or not any(
        row.get("finite_score") and not _model_ranking_block(row["model"], report["failures"])
        for row in report["models"]
    )
    if report["leaderboard_blocked"]:
        report["leaderboard"] = None
        report["close_pairs"] = []
    report["ok"] = report["integrity_ok"] and not report["suspicions"]
    if overlap:
        add_overlap(report, loaded, budget)
    if pair is not None:
        add_bootstrap(
            report, loaded, pair[0], pair[1], block, budget, n_boot=n_boot, seed=seed,
        )
    return plain(report)


def find_real_score_dirs():
    found = []
    for path in BENCHMARK_DIR.rglob("*.npz"):
        if AUDIT_DIR in path.parents or path.parent == AUDIT_DIR:
            continue
        found.append(str(path.parent))
    return sorted(set(found))


def fmt(value):
    if value is None:
        return "null"
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def render_audit_txt(report):
    lines = [
        "TrustLedger BankSim 獨立審計",
        HOLDOUT_STATEMENT,
        RANKING_RULE,
        "",
        f"分數目錄：{report.get('score_dir', '')}",
        f"模型數：{report.get('model_count', 0)}",
        f"expect_banks：{report.get('expect_banks')}",
        f"審查預算：{report.get('budget')}",
        f"完整性：{'通過' if report.get('integrity_ok') else '失敗'}",
        f"可疑結果：{len(report.get('suspicions') or [])} 項",
        "",
        "可疑結果",
    ]
    suspicions = report.get("suspicions") or []
    if not suspicions:
        lines.append("- （沒有觸發。沒有 JSON sidecar 時，這些檢查維持沉默。）")
    for item in suspicions:
        lines.append(f"- {item.get('code')} {item.get('model', '')} {item.get('model_a', '')} {item.get('model_b', '')}".rstrip())
        if item.get("detail"):
            lines.append(f"  {item['detail']}")
    lines.extend(["", "完整性失敗"])
    failures = report.get("failures") or []
    if not failures:
        lines.append("- （無）")
    for item in failures:
        lines.append(f"- {json.dumps(item, ensure_ascii=False, sort_keys=True)}")
    notes = report.get("notes") or []
    if notes:
        lines.extend(["", "附註"])
        for item in notes:
            lines.append(f"- {item.get('detail')}")
    lines.extend(["", "資料對齊"])
    shared = report.get("shared_fingerprints")
    if not shared:
        lines.append("- 沒有共同 fingerprint。")
    else:
        for field, digest in shared.items():
            lines.append(f"- {field}：{digest}")
    lines.extend(["", "各模型指標"])
    if not report.get("models"):
        lines.append("- （無）")
    for row in report.get("models") or []:
        lines.append(f"- {row['model']}")
        lines.append(f"  列數 {row.get('rows')}，詐欺數 {row.get('fraud')}，alerts {row.get('alerts')}")
        contract_metrics = row.get("contract_metrics") or {}
        own = row.get("independent_metrics") or {}
        if contract_metrics:
            lines.append(
                "  contract AP "
                f"{fmt(contract_metrics.get('average_precision'))}，"
                f"獨立 AP {fmt(own.get('average_precision'))}，"
                f"ROC AUC {fmt(own.get('roc_auc'))}"
            )
            lines.append(
                f"  TP {own.get('TP')} FP {own.get('FP')} TN {own.get('TN')} FN {own.get('FN')}，"
                f"unique scores {own.get('score_unique_values')}"
            )
        diffs = row.get("metric_differences") or {}
        if diffs:
            lines.append(f"  指標差距：{json.dumps(diffs, ensure_ascii=False, sort_keys=True)}")
        prior = row.get("previously_reported")
        if prior:
            lines.append(
                "  先前 PR #15 舊數字只供對照，不是這次測量："
                f" AP {fmt(prior.get('reported_average_precision'))}"
            )
    lines.extend(["", "榜單（完整 test 點估計）"])
    if report.get("leaderboard_blocked") or not report.get("leaderboard"):
        lines.append("- 沒有發布榜單。完整性沒過，或目錄裡沒有可用分數。")
    else:
        for row in report["leaderboard"]:
            lines.append(
                f"{row['rank']}. {row['model']}  AP {fmt(row['average_precision'])}  "
                f"TP {row['TP']}  FP {row['FP']}  FN {row['FN']}"
            )
        lines.append("排序鍵是 full_test_average_precision，不是 bootstrap 平均數。")
    close_pairs = report.get("close_pairs") or []
    lines.extend(["", "AP 接近的配對"])
    if not close_pairs:
        lines.append("- （無，或榜單未發布）")
    for pair in close_pairs:
        lines.append(
            f"- {pair['model_a']} vs {pair['model_b']}，|AP| = {fmt(pair['abs_ap_gap'])}。{pair['note']}"
        )
    lines.extend(["", "成對 bootstrap"])
    bootstrap = report.get("bootstrap")
    if not bootstrap:
        lines.append("- 這次沒有指定 --pair。")
    elif bootstrap.get("skipped"):
        lines.append(f"- 未執行：{bootstrap.get('reason')}")
    else:
        ap = bootstrap["ap"]
        tp = bootstrap["tp_at_scaled_budget"]
        lines.append(
            f"- {bootstrap['model_a']} 減 {bootstrap['model_b']}，block = {bootstrap['block']}，"
            f"block_count = {bootstrap['block_count']}"
        )
        lines.append(
            f"  AP 差的 95% CI [{fmt(ap['ci95_low'])}, {fmt(ap['ci95_high'])}]，"
            f"含 0：{ap['includes_zero']}。平均數 {fmt(ap['mean'])} 不用來排名。"
        )
        lines.append(
            f"  縮放預算下 TP 差的 95% CI [{fmt(tp['ci95_low'])}, {fmt(tp['ci95_high'])}]，"
            f"含 0：{tp['includes_zero']}。"
        )
        if ap["includes_zero"]:
            lines.append("  AP 區間含 0，不宣稱兩者有清楚差異。")
        lines.append("  完整 test 點估計：")
        for name, metrics in bootstrap["full_test_point_estimates"].items():
            lines.append(
                f"  - {name}：AP {fmt(metrics['average_precision'])}，"
                f"TP {metrics['TP']}，FP {metrics['FP']}，FN {metrics['FN']}"
            )
        lines.append(f"  {bootstrap['ranking_note']}")
    lines.extend(["", "詐欺重疊（top budget 裡的詐欺件數）"])
    overlap = report.get("overlap")
    if overlap is None:
        lines.append("- 這次沒有指定 --overlap。")
    elif isinstance(overlap, dict) and overlap.get("skipped"):
        lines.append(f"- 未執行：{overlap.get('reason')}")
    elif not overlap:
        lines.append("- 模型少於兩個，沒有配對。")
    else:
        for pair in overlap:
            lines.append(
                f"- {pair['model_a']} vs {pair['model_b']}："
                f"both {pair['both']}，only_a {pair['only_a']}，"
                f"only_b {pair['only_b']}，neither {pair['neither']}，"
                f"詐欺合計 {pair['fraud']}"
            )
    lines.extend(["", "金額切片"])
    slices = report.get("amount_slices")
    if slices is None:
        lines.append("- 這次沒有指定 --overlap。")
    elif isinstance(slices, dict) and slices.get("skipped"):
        lines.append(f"- 未執行：{slices.get('reason')}")
    elif not slices:
        lines.append("- （無）")
    else:
        for name, rows in slices.items():
            lines.append(f"- {name}")
            for row in rows:
                lines.append(
                    f"  {row['slice']}：rows {row['rows']}，fraud {row['fraud']}，"
                    f"detected {row['detected_fraud']}，missed {row['missed_fraud']}，"
                    f"FP {row['false_positives']}"
                )
    lines.append("")
    return "\n".join(lines)


def write_real_outputs(report):
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_TXT.write_text(render_audit_txt(report), encoding="utf-8")
    AUDIT_JSON.write_text(
        json.dumps(plain(report), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _save_npz(directory, name, score, y, amount, step, customer, merchant, category):
    directory.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        directory / f"{name}.npz",
        score=np.asarray(score, dtype=np.float64),
        y=np.asarray(y, dtype=np.int8),
        amount=np.asarray(amount, dtype=np.float64),
        step=np.asarray(step, dtype=np.int16),
        customer=np.asarray(customer, dtype=np.int32),
        merchant=np.asarray(merchant, dtype=np.int32),
        category=np.asarray(category, dtype=np.int16),
    )


def _synthetic_frame(seed, n=1000, fraud=80):
    rng = np.random.default_rng(seed)
    y = np.zeros(n, dtype=np.int8)
    y[:fraud] = 1
    rng.shuffle(y)
    amount = rng.uniform(1.0, 400.0, size=n)
    step = np.resize(np.arange(150, 180, dtype=np.int16), n)
    customer = rng.integers(0, 40, size=n, dtype=np.int32)
    merchant = rng.integers(0, 12, size=n, dtype=np.int32)
    category = rng.integers(0, 6, size=n, dtype=np.int16)
    return y, amount, step, customer, merchant, category


def _synthetic_score(y, seed):
    rng = np.random.default_rng(seed)
    y = np.asarray(y, dtype=np.float64)
    return (0.55 * y + 0.25 * rng.random(len(y)) + 0.05).astype(np.float64)


def _prepare_synth_root():
    if SYNTH_ROOT.exists():
        for path in sorted(SYNTH_ROOT.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    SYNTH_ROOT.mkdir(parents=True, exist_ok=True)


def _remove_synth_root():
    if not SYNTH_ROOT.exists():
        return
    for path in sorted(SYNTH_ROOT.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    SYNTH_ROOT.rmdir()


def run_self_check():
    before = (AUDIT_TXT.exists(), AUDIT_JSON.exists())
    lines = ["TrustLedger BankSim 審計 self-check", ""]
    try:
        if contract.TEST_ROWS != EXPECTED_ROWS or contract.TEST_FRAUD != EXPECTED_FRAUD:
            raise AssertionError("contract population constants drifted")
        if contract.ALERT_BUDGET != ALERT_BUDGET or contract.SIMILAR_AP != SIMILAR_AP:
            raise AssertionError("contract budget or similarity band drifted")
        if contract.fw.MERCHANT_ALPHA != 20.0:
            raise AssertionError("hand rates assume merchant alpha 20")
        contract.self_check()
        lines.append("contract.self_check：通過")
        expected = hand_step_causal_toy()
        literals = np.array([0.0, 0.0, 11.0 / 22.0, 2.0 / 3.0], dtype=np.float64)
        if not np.allclose(expected, literals, atol=1e-12, rtol=0.0):
            raise AssertionError(f"hand rates {expected.tolist()} != [0, 0, 11/22, 2/3]")
        got = contract.step_causal_merchant_rate(
            np.array([0, 0, 0, 1]),
            np.array([1, 0, 1, 0]),
            np.array([0, 0, 1, 2]),
            np.array([True, True, True, False]),
        )
        if not np.allclose(got, expected, atol=1e-12, rtol=0.0):
            raise AssertionError(f"contract rates {got.tolist()} != hand {expected.tolist()}")
        lines.append("step-causal 手算（alpha = 20，train prefix 長度 3，同一步驟的標籤互不可見）")
        lines.append("輸入：merchant [0, 0, 0, 1]，y [1, 0, 1, 0]，step [0, 0, 1, 2]")
        lines.append("手算：row0 = 0，row1 = 0，row2 = 11/22，row3 = 2/3")
        lines.append(
            "contract.step_causal_merchant_rate："
            + ", ".join(f"{value:.16g}" for value in np.asarray(got, dtype=np.float64))
        )
        lines.append("手算與 contract 的差距都低於 1e-12。預期值不是從函式輸出抄回來的。")
        lines.append("")

        tie_score = np.array([0.5, 0.5, 0.5, 0.2])
        tie_amount = np.array([1.0, 5.0, 5.0, 9.0])
        tie_y = np.array([1, 0, 1, 0])
        tie_mask = independent_topk_mask(tie_score, tie_amount, 2)
        if tie_mask.tolist() != [False, True, True, False]:
            raise AssertionError(f"tie break mask {tie_mask.tolist()}")
        if not np.array_equal(tie_mask, np.asarray(contract.topk_labels(tie_score, tie_amount, 2))):
            raise AssertionError("independent top-k disagrees with contract.topk_labels")
        tie_metrics = independent_evaluate(tie_y, tie_score, tie_amount, k=2)
        if (tie_metrics["TP"], tie_metrics["FP"], tie_metrics["TN"], tie_metrics["FN"]) != (1, 1, 1, 1):
            raise AssertionError(f"toy confusion {tie_metrics}")
        if metric_differences(contract.evaluate(tie_y, tie_score, tie_amount, k=2), tie_metrics):
            raise AssertionError("toy contract.evaluate disagreed with the independent counts")
        lines.append("平手規則抽樣：分數相同則金額高的在前，再相同則列索引小的在前。TP/FP/TN/FN = 1/1/1/1。")

        _prepare_synth_root()
        y, amount, step, customer, merchant, category = _synthetic_frame(11)
        happy = SYNTH_ROOT / "happy"
        _save_npz(happy, "alpha", _synthetic_score(y, 21), y, amount, step, customer, merchant, category)
        _save_npz(happy, "beta", _synthetic_score(y, 22), y, amount, step, customer, merchant, category)
        happy_report = audit_directory(happy, expect_banks=False, budget=ALERT_BUDGET, overlap=True)
        if not happy_report["integrity_ok"]:
            raise AssertionError(f"happy path failed: {happy_report['failures']}")
        if happy_report["leaderboard_blocked"] or len(happy_report["leaderboard"]) != 2:
            raise AssertionError("happy path did not keep a point-estimate order internally")
        aps = [row["average_precision"] for row in happy_report["leaderboard"]]
        if aps != sorted(aps, reverse=True):
            raise AssertionError("leaderboard was not sorted by full-test AP")
        if any(row["alerts"] != ALERT_BUDGET for row in happy_report["models"]):
            raise AssertionError("happy path alert count was not 919")
        overlap = happy_report["overlap"]
        if len(overlap) != 1 or overlap[0]["both"] + overlap[0]["only_a"] + overlap[0]["only_b"] + overlap[0]["neither"] != int(np.sum(y)):
            raise AssertionError(f"overlap counts {overlap}")
        if set(happy_report["amount_slices"]) != {"alpha", "beta"}:
            raise AssertionError("amount slices missing")
        lines.append(
            f"合成 npz 配對：{happy}（expect_banks=false，列數 {len(y)}，預算 {ALERT_BUDGET}）"
        )
        lines.append("對齊、有限分數、top-919、contract.evaluate 與獨立指標、fingerprint：通過。")
        lines.append("合成資料的內部品檢有做點估計排序，但沒有寫成 BankSim 榜單。")

        mismatch = SYNTH_ROOT / "mismatch"
        flipped = y.copy()
        flipped[0] = np.int8(1 - int(flipped[0]))
        _save_npz(mismatch, "alpha", _synthetic_score(y, 21), y, amount, step, customer, merchant, category)
        _save_npz(mismatch, "beta", _synthetic_score(y, 22), flipped, amount, step, customer, merchant, category)
        mismatch_report = audit_directory(mismatch, expect_banks=False, budget=ALERT_BUDGET)
        mismatch_fields = {
            (item["code"], item.get("field")) for item in mismatch_report["failures"]
        }
        if ("alignment", "y") not in mismatch_fields:
            raise AssertionError(f"y mismatch was not detected: {mismatch_report['failures']}")
        if not mismatch_report["leaderboard_blocked"]:
            raise AssertionError("y mismatch still produced a leaderboard")
        lines.append("兩份檔案的 y 不同：有抓到 alignment / y，而且沒有發布榜單。")

        short = SYNTH_ROOT / "short_budget"
        short_n = 25
        short_frame = _synthetic_frame(3, n=short_n, fraud=4)
        _save_npz(
            short,
            "short",
            _synthetic_score(short_frame[0], 4),
            *short_frame,
        )
        short_report = audit_directory(short, expect_banks=False, budget=ALERT_BUDGET)
        budget_hits = [item for item in short_report["failures"] if item["code"] == "alert_budget"]
        if len(budget_hits) != 1 or budget_hits[0]["alerts"] == ALERT_BUDGET:
            raise AssertionError(f"alert budget miss was not detected: {short_report['failures']}")
        if any(item["code"] == "alignment" for item in short_report["failures"]):
            raise AssertionError("short file unexpectedly failed alignment")
        lines.append(
            f"短檔列數 {short_n}，top-919 的 alert 數是 {budget_hits[0]['alerts']}，"
            "不是要求的 919：有抓到 alert_budget。"
        )

        suspect = SYNTH_ROOT / "suspect"
        perfect = y.astype(np.float64)
        _save_npz(suspect, "copy_a", perfect, y, amount, step, customer, merchant, category)
        _save_npz(suspect, "copy_b", perfect, y, amount, step, customer, merchant, category)
        (suspect / "copy_a.json").write_text(json.dumps({
            "model": "copy_a",
            "track": "A",
            "features": ["amount", "merchant_rate"],
            "note": "This test is an untouched holdout.",
            "test_rows": 10,
            "test_fraud": 1,
            "test": {"average_precision": 1.0, "n": 10},
        }, indent=2) + "\n", encoding="utf-8")
        (suspect / "copy_b.json").write_text(json.dumps({
            "model": "copy_b",
            "test": {"average_precision": 0.2},
        }, indent=2) + "\n", encoding="utf-8")
        suspect_report = audit_directory(suspect, expect_banks=False, budget=ALERT_BUDGET)
        codes = {item["code"] for item in suspect_report["suspicions"]}
        expected_codes = {
            "identical_scores",
            "ap_above_0_999",
            "missing_leakage_status",
            "test_length_drift",
            "track_a_merchant_rate",
            "untouched_holdout_claim",
        }
        if not expected_codes.issubset(codes):
            raise AssertionError(f"suspicion codes {codes} missing {expected_codes - codes}")
        lines.append("JSON sidecar 存在時，六項可疑結果檢查都會觸發。")

        silent = SYNTH_ROOT / "silent"
        _save_npz(silent, "copy_a", perfect, y, amount, step, customer, merchant, category)
        _save_npz(silent, "copy_b", perfect, y, amount, step, customer, merchant, category)
        silent_report = audit_directory(silent, expect_banks=False, budget=ALERT_BUDGET)
        if silent_report["suspicions"]:
            raise AssertionError(f"suspicions fired without JSON: {silent_report['suspicions']}")
        if identical_score_arrays(perfect, perfect, None, None) is not None:
            raise AssertionError("identical_score_arrays fired without sidecars")
        if ap_above_0_999(None, measured=1.0) is not None:
            raise AssertionError("ap_above_0_999 fired without a sidecar")
        if missing_leakage_status(None) is not None:
            raise AssertionError("missing_leakage_status fired without a sidecar")
        if test_length_drift(None, observed_rows=1, observed_fraud=1) is not None:
            raise AssertionError("test_length_drift fired without a sidecar")
        if merchant_rate_as_track_a(None) is not None:
            raise AssertionError("merchant_rate_as_track_a fired without a sidecar")
        if untouched_holdout_claim(None) is not None:
            raise AssertionError("untouched_holdout_claim fired without a sidecar")
        lines.append("沒有 JSON sidecar 時，上述檢查維持沉默，即使分數完全相同、AP 也是 1。")

        if missing_leakage_status({"leakage_status": "step_causal"}) is not None:
            raise AssertionError("present leakage_status was flagged")
        if ap_above_0_999({"test": {"average_precision": 0.95}}) is not None:
            raise AssertionError("AP 0.95 was treated as perfect")
        if merchant_rate_as_track_a({"track": "A", "features": ["amount", "cat_cdf"]}) is not None:
            raise AssertionError("Track A without merchant rate was flagged")
        if merchant_rate_as_track_a({"track": "B", "features": ["merchant_rate"]}) is not None:
            raise AssertionError("Track B merchant rate was flagged as Track A")
        if merchant_rate_as_track_a({"note": "Track A has no merchant fraud rate"}) is not None:
            raise AssertionError("excluded merchant rate was flagged")
        if untouched_holdout_claim({"note": "不可以把它寫成獨立、未接觸的 holdout。"}) is not None:
            raise AssertionError("negated holdout sentence was flagged")
        if untouched_holdout_claim({"note": "This is not a pristine blind holdout."}) is not None:
            raise AssertionError("negated pristine claim was flagged")
        if test_length_drift({
            "test_rows": EXPECTED_ROWS,
            "test_fraud": EXPECTED_FRAUD,
            "test": {"n": EXPECTED_ROWS},
        }) is not None:
            raise AssertionError("frozen population was treated as drift")
        lines.append("負向對照：正確的 leakage_status、Track A、否定句與凍結人口數都沒有誤報。")

        boot = audit_directory(
            happy,
            expect_banks=False,
            budget=ALERT_BUDGET,
            pair=("alpha", "beta"),
            block="customer",
            n_boot=8,
            seed=1,
        )
        if boot["bootstrap"] is None or boot["bootstrap"].get("skipped"):
            raise AssertionError(f"bootstrap did not run: {boot['bootstrap']}")
        if "includes_zero" not in boot["bootstrap"]["ap"]:
            raise AssertionError("bootstrap CI missing")
        if boot["bootstrap"]["block_count"] != len(np.unique(customer)):
            raise AssertionError("block_count mismatch")
        if "full_test_point_estimates" not in boot["bootstrap"]:
            raise AssertionError("full-test point estimates missing")
        reversed_board = rank_models([
            {
                "model": "low",
                "independent_metrics": {"average_precision": 0.2, "roc_auc": 0.4, "TP": 1, "FP": 1, "TN": 1, "FN": 1, "alerts": 2, "score_unique_values": 2},
            },
            {
                "model": "high",
                "independent_metrics": {"average_precision": 0.8, "roc_auc": 0.9, "TP": 2, "FP": 0, "TN": 1, "FN": 0, "alerts": 2, "score_unique_values": 2},
            },
        ])
        if [row["model"] for row in reversed_board] != ["high", "low"]:
            raise AssertionError("ranking followed something other than AP")
        lines.append(
            "合成 customer block bootstrap：有 CI、是否含 0、block_count 與完整 test 點估計。"
            "排序函式不讀 bootstrap 平均數。"
        )
        rendered = render_audit_txt(boot)
        for snippet in ("95% CI", "block_count", "完整 test 點估計", HOLDOUT_STATEMENT):
            if snippet not in rendered:
                raise AssertionError(f"audit text missing {snippet}")
        mismatch_text = render_audit_txt(mismatch_report)
        if "沒有發布榜單" not in mismatch_text:
            raise AssertionError("mismatched y still rendered a leaderboard")
        lines.append("審計文字有寫出 CI、點估計，以及 y 不一致時不發布榜單。")

        real_dirs = find_real_score_dirs()
        lines.append("")
        if real_dirs:
            lines.append("真實分數目錄：" + "，".join(real_dirs))
            lines.append("self-check 沒有把這些目錄寫成榜單。")
        else:
            lines.append(
                "真實分數目錄：工作樹的 evaluation/research/benchmark 底下沒有其他 agent 的 *.npz。"
            )
            lines.append("沒有編造 BankSim 榜單，也沒有填先前 PR #15 的舊數字。")
        lines.append("")
        lines.append("結果：PASS")
        lines.append("合成檔在 /tmp/tl-audit-selfcheck，通過後會刪除，不在 repo 裡。")
        _remove_synth_root()
        if (AUDIT_TXT.exists(), AUDIT_JSON.exists()) != before:
            raise AssertionError("self-check wrote AUDIT.txt or audit_report.json")
        SELF_CHECK_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 0
    except Exception as exc:
        lines.append("")
        lines.append(f"結果：FAIL")
        lines.append(str(exc))
        SELF_CHECK_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"self-check failed: {exc}", file=sys.stderr)
        return 1


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Audit BankSim *.npz prediction files.")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--scores", type=Path)
    parser.add_argument("--expect-banks", default="true", choices=("true", "false"))
    parser.add_argument("--pair", nargs=2, metavar=("NAME_A", "NAME_B"))
    parser.add_argument("--block", choices=("customer", "step"))
    parser.add_argument("--overlap", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.self_check:
        if args.scores or args.pair or args.block or args.overlap:
            print("--self-check 不能和其他模式一起用。", file=sys.stderr)
            return 2
        return run_self_check()
    if args.scores is None:
        print("需要 --self-check，或 --scores DIR。", file=sys.stderr)
        return 2
    if bool(args.pair) != bool(args.block):
        print("--pair NAME_A NAME_B 和 --block customer|step 要一起用。", file=sys.stderr)
        return 2
    expect_banks = args.expect_banks == "true"
    report = audit_directory(
        args.scores,
        expect_banks=expect_banks,
        budget=ALERT_BUDGET,
        pair=tuple(args.pair) if args.pair else None,
        block=args.block,
        overlap=args.overlap,
    )
    write_real_outputs(report)
    print(render_audit_txt(report))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
