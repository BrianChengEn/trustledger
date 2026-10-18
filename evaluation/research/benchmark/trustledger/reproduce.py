"""Reproduce TrustLedger baselines and measure merchant-rate leakage.

Fits only on steps 0-119. Does not retune, does not save model binaries,
and does not treat steps 150-179 as an unseen blind test.
"""

from __future__ import annotations

import gc
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent.parent
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))

import contract  # noqa: E402
import run_framework as fw  # noqa: E402

ROOT = Path(__file__).resolve().parent
SCORES = ROOT / "scores"
EXPECTED_HGB = {
    "max_iter": 80,
    "learning_rate": 0.08,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 40,
    "l2_regularization": 0.1,
    "random_state": 20261017,
}
ARCHIVED = ("prod_rules", "pr14_mapped_hgb", "v2_enriched_sqrt", "v2_merchant")
RATE_TOL = 1e-8


def log(message):
    print(message, file=sys.stderr, flush=True)


def peak_rss_bytes():
    rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return rss
    return rss * 1024


def json_default(value):
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value).__name__)


def shrunk_assignment(merchant, y, mask, alpha):
    """One rate per row from a single aggregate of rows inside mask."""
    merchant = np.asarray(merchant)
    y = np.asarray(y, dtype=np.float64)
    mask = np.asarray(mask, dtype=bool)
    n_merch = int(merchant.max()) + 1
    counts = np.bincount(merchant[mask], minlength=n_merch).astype(np.float64)
    frauds = np.bincount(merchant[mask], weights=y[mask], minlength=n_merch).astype(np.float64)
    global_rate = float(y[mask].mean()) if int(mask.sum()) else 0.0
    shrunk = (frauds + alpha * global_rate) / (counts + alpha)
    return shrunk[merchant]


def own_label_gap(built):
    merchant = built["merchant"]
    y = built["y"].astype(np.float64)
    train = built["train"]
    alpha = fw.MERCHANT_ALPHA
    n_merch = int(merchant.max()) + 1
    counts = np.bincount(merchant[train], minlength=n_merch).astype(np.float64)
    frauds = np.bincount(merchant[train], weights=y[train], minlength=n_merch).astype(np.float64)
    n_train = float(train.sum())
    sum_y = float(y[train].sum())
    global_rate = sum_y / n_train
    assigned = ((frauds + alpha * global_rate) / (counts + alpha))[merchant]
    loo_counts = counts[merchant] - 1.0
    loo_frauds = frauds[merchant] - y
    loo_global = (sum_y - y) / (n_train - 1.0)
    loo = (loo_frauds + alpha * loo_global) / (loo_counts + alpha)
    gap = np.abs(assigned - loo)
    train_gap = gap[train]
    fraud = train & (built["y"] == 1)
    return {
        "train_rows": int(train.sum()),
        "train_rows_own_label_gap_gt_0": int(np.sum(train_gap > 0.0)),
        "train_own_label_gap_mean_abs": float(train_gap.mean()),
        "train_fraud_own_label_gap_mean_abs": float(gap[fraud].mean()),
        "train_own_label_gap_max_abs": float(train_gap.max()),
        "frozen_vs_train_aggregate_max_abs": float(np.max(np.abs(assigned - built["merchant_rate"]))),
    }


def later_training_label_gap(built):
    """Frozen all-train rate versus a rate that stops at the row's own step.

    The comparison rate includes the row's own label and other labels from
    the same step. A nonzero gap is information from later training steps.
    """
    merchant = np.asarray(built["merchant"])
    y = np.asarray(built["y"], dtype=np.float64)
    step = np.asarray(built["step"])
    n_train = int(built["train"].sum())
    alpha = fw.MERCHANT_ALPHA
    n_merch = int(merchant.max()) + 1
    counts = np.zeros(n_merch, dtype=np.float64)
    frauds = np.zeros(n_merch, dtype=np.float64)
    g_count = 0.0
    g_fraud = 0.0
    inclusive = np.empty(n_train, dtype=np.float64)
    i = 0
    while i < n_train:
        j = i + 1
        cur = int(step[i])
        while j < n_train and int(step[j]) == cur:
            j += 1
        counts += np.bincount(merchant[i:j], minlength=n_merch).astype(np.float64)
        frauds += np.bincount(merchant[i:j], weights=y[i:j], minlength=n_merch).astype(np.float64)
        g_count += float(j - i)
        g_fraud += float(y[i:j].sum())
        shrunk = (frauds + alpha * (g_fraud / g_count)) / (counts + alpha)
        inclusive[i:j] = shrunk[merchant[i:j]]
        i = j
    gap = np.abs(built["merchant_rate"][:n_train] - inclusive)
    return {
        "train_rows": n_train,
        "train_rows_changed_by_later_labels": int(np.sum(gap > RATE_TOL)),
        "later_training_label_gap_mean_abs": float(gap.mean()),
        "later_training_label_gap_max_abs": float(gap.max()),
    }


def changed_rows(reference, alternative, mask):
    delta = np.abs(np.asarray(reference)[mask] - np.asarray(alternative)[mask])
    return int(np.sum(delta > RATE_TOL)), float(delta.max()) if delta.size else 0.0


def leakage_measurements(built):
    alpha = fw.MERCHANT_ALPHA
    merchant = built["merchant"]
    y = built["y"]
    step = built["step"]
    train = built["train"]
    select = built["select"]
    confirm = built["confirm"]
    test = built["test"]
    frozen = built["merchant_rate"]
    started = time.perf_counter()
    causal = contract.step_causal_merchant_rate(merchant, y, step, train, alpha)
    causal_seconds = time.perf_counter() - started
    started = time.perf_counter()
    expanding = contract.expanding_merchant_rate(merchant, y, step, alpha)
    expanding_seconds = time.perf_counter() - started

    post = ~train
    post_gap = np.abs(causal[post] - frozen[post])
    if float(post_gap.max()) > RATE_TOL:
        raise SystemExit("step_causal rows after step 119 are not the frozen 0-119 rate")
    test_gap = np.abs(causal[test] - frozen[test])
    if float(test_gap.max()) > RATE_TOL:
        raise SystemExit("step_causal test rate uses information outside steps 0-119")

    own = own_label_gap(built)
    later = later_training_label_gap(built)
    train_only = shrunk_assignment(merchant, y, train, alpha)
    with_select = shrunk_assignment(merchant, y, train | select, alpha)
    with_confirm = shrunk_assignment(merchant, y, train | confirm, alpha)
    with_test = shrunk_assignment(merchant, y, train | test, alpha)
    through_confirm = shrunk_assignment(merchant, y, train | select | confirm, alpha)
    select_rows, select_max = changed_rows(frozen, with_select, test)
    confirm_rows, confirm_max = changed_rows(frozen, with_confirm, test)
    test_rows, test_max = changed_rows(frozen, with_test, test)
    frozen_vs_train = float(np.max(np.abs(frozen - train_only)))
    expanding_vs_frozen_test = np.abs(expanding[test] - frozen[test])
    expanding_vs_through_confirm = np.abs(expanding[test] - through_confirm[test])
    causal_train_gap = np.abs(causal[train] - frozen[train])
    expanding_train_gap = np.abs(expanding[train] - causal[train])
    return causal, expanding, {
        "rate_equality_tolerance": RATE_TOL,
        "own_label": own,
        "later_training_labels": later,
        "frozen_vs_train_only_max_abs": frozen_vs_train,
        "select_confirm_test_labels_in_frozen_rate": frozen_vs_train > RATE_TOL,
        "test_rows_whose_rate_would_change_if_select_labels_were_added": select_rows,
        "max_abs_if_select_labels_were_added": select_max,
        "test_rows_whose_rate_would_change_if_confirm_labels_were_added": confirm_rows,
        "max_abs_if_confirm_labels_were_added": confirm_max,
        "test_rows_whose_rate_would_change_if_test_labels_were_added": test_rows,
        "max_abs_if_test_labels_were_added": test_max,
        "step_causal_seconds": causal_seconds,
        "expanding_seconds": expanding_seconds,
        "step_causal_post_train_max_abs_diff_from_frozen": float(post_gap.max()),
        "step_causal_test_max_abs_diff_from_frozen": float(test_gap.max()),
        "step_causal_train_max_abs_diff_from_frozen": float(causal_train_gap.max()),
        "step_causal_train_rows_diff_from_frozen": int(np.sum(causal_train_gap > RATE_TOL)),
        "expanding_train_max_abs_diff_from_step_causal": float(expanding_train_gap.max()),
        "expanding_test_rows_diff_from_frozen": int(np.sum(expanding_vs_frozen_test > RATE_TOL)),
        "expanding_test_max_abs_diff_from_frozen": float(expanding_vs_frozen_test.max()),
        "expanding_test_rows_diff_from_steps_0_149_aggregate": int(
            np.sum(expanding_vs_through_confirm > RATE_TOL)
        ),
        "expanding_test_max_abs_diff_from_steps_0_149_aggregate": float(
            expanding_vs_through_confirm.max()
        ),
        "step_causal_test_rate_uses_only_steps_0_119": True,
        "expanding_information_set": (
            "different_from_original_frozen: each row uses completed earlier steps, "
            "so test rows can see labels from steps 120-149 and from earlier test steps"
        ),
    }


def fit_split_scores(matrix, built, weight_mode):
    model, scores, train_seconds, infer_seconds, infer_rows = fw.fit_hgb(
        matrix[built["train"]],
        built["y"][built["train"]],
        {
            "select": matrix[built["select"]],
            "confirm": matrix[built["confirm"]],
            "test": matrix[built["test"]],
        },
        weight_mode,
    )
    # Train rows are not scored. NaN marks that the fit was not asked to score them.
    del model
    full = np.full(len(built["y"]), np.nan, dtype=np.float64)
    for split in ("select", "confirm", "test"):
        values = np.asarray(scores[split], dtype=np.float64)
        if len(values) != int(built[split].sum()):
            raise SystemExit(f"{split} score length does not match the mask")
        full[built[split]] = values
        if not np.isfinite(values).all():
            raise SystemExit(f"non-finite {split} scores")
    return full, float(train_seconds), float(infer_seconds), int(infer_rows)


def reproduction_status(name, metrics):
    compared = contract.compare_reported(name, metrics)
    if compared is None:
        return None
    compared = dict(compared)
    counts_exact = (
        compared["tp_match"] and compared["fp_match"]
        and compared["tn_match"] and compared["fn_match"]
    )
    ap_diff = float(compared["ap_abs_diff"])
    if counts_exact and ap_diff == 0.0:
        status = "MATCH"
    elif counts_exact and ap_diff < 1e-4:
        status = "BLAS_DRIFT"
    else:
        status = "MISMATCH"
    compared["reproduction_status"] = status
    return compared


def operating_view(built, full):
    test = built["test"]
    y = built["y"][test]
    amount = built["amount"][test]
    pred = contract.topk_labels(full[test], amount)
    return {
        "pred": pred,
        "amount_slices": contract.amount_slice_table(y, pred, amount),
        "category_breakdown": contract.category_breakdown(
            y, pred, built["native"][test], built["native_names"],
        ),
    }


def fraud_overlap(y, pred_a, pred_b):
    fraud = np.asarray(y).astype(bool)
    pred_a = np.asarray(pred_a).astype(bool)
    pred_b = np.asarray(pred_b).astype(bool)
    counts = {
        "both": int(np.sum(fraud & pred_a & pred_b)),
        "only_a": int(np.sum(fraud & pred_a & ~pred_b)),
        "only_b": int(np.sum(fraud & ~pred_a & pred_b)),
        "neither": int(np.sum(fraud & ~pred_a & ~pred_b)),
    }
    if sum(counts.values()) != int(fraud.sum()):
        raise SystemExit("fraud overlap does not partition the fraud rows")
    return counts


def finish_model(name, full, built, meta):
    view = operating_view(built, full)
    meta["amount_slices"] = view["amount_slices"]
    meta["category_breakdown"] = view["category_breakdown"]
    test = built["test"]
    preview = contract.evaluate(built["y"][test], full[test], built["amount"][test])
    compared = reproduction_status(name, preview)
    meta["reproduction_status"] = None if compared is None else compared["reproduction_status"]
    body = contract.save_prediction(SCORES, name, built, full, meta)
    saved = body["test"]
    if saved["TP"] != preview["TP"] or saved["FP"] != preview["FP"]:
        raise SystemExit(f"{name} saved confusion counts diverged")
    if saved["average_precision"] != preview["average_precision"]:
        raise SystemExit(f"{name} saved average precision diverged")
    confirmed = reproduction_status(name, saved)
    confirmed_status = None if confirmed is None else confirmed["reproduction_status"]
    if confirmed_status != meta["reproduction_status"]:
        raise SystemExit(f"{name} reproduction status diverged from the saved metrics")
    return body, confirmed, view["pred"]


def _fmt(value):
    if isinstance(value, float):
        return json.dumps(value)
    return str(value)


def write_notes(audit):
    enc = audit["merchant_encoding_audit"]
    leak = audit["leakage_measurements"]
    own = leak["own_label"]
    later = leak["later_training_labels"]
    models = audit["models"]
    original = models["v2_merchant"]["test"]
    causal = models["v2_merchant_step_causal"]["test"]
    expanding = models["v2_merchant_expanding"]["test"]
    rules = models["prod_rules"]["test"]
    own_enters = own["train_own_label_gap_max_abs"] > 0.0
    later_enters = later["train_rows_changed_by_later_labels"] > 0
    outside_enters = leak["select_confirm_test_labels_in_frozen_rate"]
    unseen = int(enc["test_unseen_merchant_ids"])
    ap_delta = causal["average_precision"] - original["average_precision"]
    tp_delta = causal["TP"] - original["TP"]
    fp_delta = causal["FP"] - original["FP"]
    point_same = ap_delta == 0.0 and tp_delta == 0 and fp_delta == 0
    overlap_causal = audit["fraud_overlap_top919"]["v2_merchant_vs_v2_merchant_step_causal"]
    overlap_enriched = audit["fraud_overlap_top919"]["v2_merchant_vs_v2_enriched_sqrt"]
    earlier_test_rows = leak["expanding_test_rows_diff_from_steps_0_149_aggregate"]
    if earlier_test_rows > 0:
        earlier_test_sentence = (
            "這個數量大於 0，所以較晚的 test 列還看得到更早 test step 的標籤，不只 120–149。"
        )
    else:
        earlier_test_sentence = (
            "這個數量是 0。以這次測量，expanding 的 test 率沒有偏離 steps 0–149 的一次聚合；"
            "資訊集仍然不同，因為作法允許看到 steps 120–149。"
        )
    lines = [
        "TrustLedger 基線重現與 merchant rate 洩漏審計",
        "",
        "這份筆記只記錄這次測量。不建議部署任何模型。",
        "steps 150–179 已經在 PR #14 與 PR #15 看過。這是可重現對照，不是未接觸的盲測。",
        "沒有依 test 分數調整模型。HGB 只用 fw.fit_hgb 的固定參數：",
        "max_iter 80、learning_rate 0.08、max_leaf_nodes 31、min_samples_leaf 40、",
        "l2_regularization 0.1、random_state 20261017。",
        "",
        "人口數",
        "TRAIN steps 0–119：374,914 筆、4,800 件詐欺。",
        "SELECT steps 120–134：53,722 筆、600 件詐欺。",
        "CONFIRM steps 135–149：54,701 筆、600 件詐欺。",
        "TEST steps 150–179：111,306 筆、1,200 件詐欺。",
        "人口數和契約不一致時，這次執行會停止。這次相符。",
        "",
        "original_frozen 有沒有把標籤放進特徵",
        "original_frozen 是 v2_merchant 的 merchant_rate，也就是 PR #15 的凍結訓練聚合。",
        "merchant_rate 是商家詐欺率：用訓練期的詐欺筆數做收縮，再填回每一列。",
        "",
        "1. 訓練列自己的標籤：" + ("有進入。" if own_enters else "測量上看不到進入。"),
        "   凍結率把該列自己的 fraud 標籤算進該商家的聚合。",
        "   拿掉該列再算一次的絕對差距（own-label gap）：",
        f"   訓練列平均 {_fmt(own['train_own_label_gap_mean_abs'])}",
        f"   訓練詐欺列平均 {_fmt(own['train_fraud_own_label_gap_mean_abs'])}",
        f"   訓練列最大 {_fmt(own['train_own_label_gap_max_abs'])}",
        f"   差距大於 0 的訓練列：{own['train_rows_own_label_gap_gt_0']} / {own['train_rows']}",
        "",
        "2. 較晚的訓練標籤：" + ("有進入。" if later_enters else "測量上沒有進入。"),
        "   對照是「含該列所在 step、但不含更晚 step」的商家率。",
        "   這個對照仍含自己的標籤與同一個 step 的其他標籤，所以差距只來自更晚的訓練 step。",
        f"   被改變的訓練列：{later['train_rows_changed_by_later_labels']} / {later['train_rows']}",
        f"   平均絕對差 {_fmt(later['later_training_label_gap_mean_abs'])}",
        f"   最大絕對差 {_fmt(later['later_training_label_gap_max_abs'])}",
        "",
        "3. select、confirm、test 的標籤：" + ("有進入。" if outside_enters else "沒有進入。"),
        "   凍結率與只用 steps 0–119 重算的率，最大絕對差是 "
        f"{_fmt(leak['frozen_vs_train_only_max_abs'])}。",
        "   契約審計的 select_labels_included、confirm_labels_included、test_labels_included 都是 0。",
        "   上面的最大絕對差是這次實際比較的結果，不是只抄這三個欄位。",
        "   若把 select 標籤加進聚合，test 會有 "
        f"{leak['test_rows_whose_rate_would_change_if_select_labels_were_added']} 列改變，"
        f"最大絕對差 {_fmt(leak['max_abs_if_select_labels_were_added'])}。",
        "   若改加 confirm 標籤，test 會有 "
        f"{leak['test_rows_whose_rate_would_change_if_confirm_labels_were_added']} 列改變，"
        f"最大絕對差 {_fmt(leak['max_abs_if_confirm_labels_were_added'])}。",
        "   若改加 test 標籤，test 會有 "
        f"{leak['test_rows_whose_rate_would_change_if_test_labels_were_added']} 列改變，"
        f"最大絕對差 {_fmt(leak['max_abs_if_test_labels_were_added'])}。",
        "   這些是反事實。凍結特徵本身沒有用到這三個切分的標籤。",
        "",
        "test 商家有沒有在訓練出現過",
        f"test 未見過的 merchant id：{unseen}。",
        f"落在未見過 merchant 的 test 列：{enc['test_rows_unseen_merchant']}。",
        f"訓練筆數少於 20 的 test 列：{enc['test_rows_merchant_train_count_below_20']}，",
        f"其中詐欺 {enc['test_fraud_merchant_train_count_below_20']}。",
        f"訓練筆數至少 20 的 test 詐欺：{enc['test_fraud_merchant_train_count_at_least_20']}。",
    ]
    if unseen == 0:
        lines.append(
            "這個切分沒有未見過的 test 商家，不能用它證明新商家泛化。"
        )
    else:
        lines.append(
            f"有 {unseen} 個 test merchant id 在訓練沒出現過。這裡只報告這個數量，不把它寫成新商家泛化已經成立。"
        )
    lines.extend([
        "",
        "step_causal 相對 original_frozen",
        "step_causal 的訓練列只用更早的 step。同一個 step 的標籤彼此看不見。",
        "select、confirm、test 仍使用凍結的 steps 0–119 聚合，不含這三個切分的標籤。",
        "step 120 之後與凍結率的最大絕對差："
        f"{_fmt(leak['step_causal_post_train_max_abs_diff_from_frozen'])}。",
        "test 與凍結率的最大絕對差："
        f"{_fmt(leak['step_causal_test_max_abs_diff_from_frozen'])}。",
        "因此 step_causal 的 test 特徵沒有使用 steps 120 以後的標籤。",
        "訓練列與凍結率的最大絕對差："
        f"{_fmt(leak['step_causal_train_max_abs_diff_from_frozen'])}，",
        f"不同的訓練列有 {leak['step_causal_train_rows_diff_from_frozen']}。",
        "兩個模型的訓練特徵不同，所以 test 分數可以不同；這不是 test 標籤洩漏。",
        "",
        f"original_frozen test AP {_fmt(original['average_precision'])}，"
        f"TP {original['TP']}，FP {original['FP']}。",
        f"step_causal test AP {_fmt(causal['average_precision'])}，"
        f"TP {causal['TP']}，FP {causal['FP']}。",
        f"step_causal 減 original_frozen：AP {_fmt(ap_delta)}，TP {tp_delta}，FP {fp_delta}。",
        (
            "test AP、TP、FP 的點估計都沒有改變。"
            if point_same
            else (
                "test 點估計有改變。"
                + (
                    "AP 絕對差小於 0.01，契約會先把這個 AP 差距看成接近。"
                    if abs(ap_delta) < 0.01
                    else ""
                )
                + "這次沒有做 bootstrap，所以不把這個差距說成統計上已經分得出來。"
            )
        ),
        "詐欺重疊只算 test 的 1,200 件詐欺，警報是分數最高的 919 筆。",
        "A 是 v2_merchant，B 是 v2_merchant_step_causal。",
        f"兩邊都抓到 {overlap_causal['both']}，只有 A {overlap_causal['only_a']}，"
        f"只有 B {overlap_causal['only_b']}，兩邊都沒抓到 {overlap_causal['neither']}。",
        "",
        "expanding 分開報告",
        "expanding 不是 PR #15 的重現，資訊集不同，不能取代 original_frozen。",
        "每一列只用已經結束的較早 step。test 列因此看得到 steps 120–149 的標籤。",
        f"與凍結率不同的 test 列：{leak['expanding_test_rows_diff_from_frozen']}，"
        f"最大絕對差 {_fmt(leak['expanding_test_max_abs_diff_from_frozen'])}。",
        "與「steps 0–149 一次聚合」不同的 test 列："
        f"{leak['expanding_test_rows_diff_from_steps_0_149_aggregate']}，"
        f"最大絕對差 {_fmt(leak['expanding_test_max_abs_diff_from_steps_0_149_aggregate'])}。",
        earlier_test_sentence,
        f"expanding 的訓練列與 step_causal 訓練列最大絕對差："
        f"{_fmt(leak['expanding_train_max_abs_diff_from_step_causal'])}。",
        f"expanding test AP {_fmt(expanding['average_precision'])}，"
        f"TP {expanding['TP']}，FP {expanding['FP']}。",
        "這個數字另列，沒有拿來覆蓋 v2_merchant 的重現結果。",
        "",
        "確認延遲假設",
        "BankSim 沒有標籤延遲欄位。兩種修正都是假設，不是資料裡的事實。",
        "凍結特徵假設每一筆訓練標籤在 step 120 之前都已經知道。",
        "expanding 假設一筆標籤在它自己的 step 結束時知道，而且在下一個 step 開始前可以使用。",
        "step_causal 與 expanding 都看不到同一個 step 的其他標籤。",
        "original_frozen 則把整個 steps 0–119 的標籤，包含較晚的訓練列與該列自己的標籤，放進訓練特徵。",
        "",
        "四個舊模型的重現",
        "MATCH 是 TP、FP、TN、FN 與 Average Precision 都和 PREVIOUSLY_REPORTED 相同。",
        "BLAS_DRIFT 是這四個筆數相同，而且 AP 絕對差小於 1e-4。",
        "MISMATCH 是筆數或 AP 不同。保留這次測量，沒有改分數去貼舊數字。",
    ])
    for name in ARCHIVED:
        row = audit["compare_reported"][name]
        lines.append(
            f"{name}：{row['reproduction_status']}，"
            f"測量 AP {_fmt(row['measured_average_precision'])}，"
            f"舊 AP {_fmt(row['reported_average_precision'])}，"
            f"AP 絕對差 {_fmt(row['ap_abs_diff'])}，"
            f"TP 相同={row['tp_match']}，FP 相同={row['fp_match']}，"
            f"TN 相同={row['tn_match']}，FN 相同={row['fn_match']}。"
        )
    lines.extend([
        f"prod_rules 是 0/1 分數，test 的 unique score 數量是 {rules['score_unique_values']}。",
        "沒有把 0/1 做成機率。平手時分數高的在前，其次金額高的在前，再來是列索引小的在前。",
        "",
        "v2_enriched_sqrt 沒有 merchant_rate。它和 v2_merchant 的詐欺重疊：",
        "A 是 v2_merchant，B 是 v2_enriched_sqrt。",
        f"兩邊都抓到 {overlap_enriched['both']}，只有 A {overlap_enriched['only_a']}，"
        f"只有 B {overlap_enriched['only_b']}，兩邊都沒抓到 {overlap_enriched['neither']}。",
        "",
        "金額切片是 [0,20)、[20,250)、>=250。250 是現行規則的金額門檻。",
        "每個模型的金額切片與 native category 分解都在 audit.json，也在該模型的 json。",
        "",
        "時間與記憶體",
        f"特徵建立 {audit['timings']['feature_build_seconds']:.3f} 秒。",
        f"peak RSS {audit['peak_rss_bytes']} bytes。",
    ])
    for name in (
        "prod_rules", "pr14_mapped_hgb", "v2_enriched_sqrt",
        "v2_merchant", "v2_merchant_step_causal", "v2_merchant_expanding",
    ):
        timing = models[name]["timing"]
        lines.append(
            f"{name}：特徵 {timing['feature_seconds']:.3f} 秒，"
            f"fit {timing['fit_seconds']:.3f} 秒，"
            f"predict {timing['predict_seconds']:.3f} 秒。"
        )
    lines.extend([
        "",
        "若 step_causal 與 original_frozen 的 test 點估計不同，merchant 特徵的對外數字以 step_causal 為準。",
        "original_frozen 只保留為 PR #15 的重現。這不是部署建議。",
        "這次沒有建議把任何模型放到生產環境。",
        "",
    ])
    (ROOT / "NOTES.txt").write_text("\n".join(lines), encoding="utf-8")


def compare_line(name, metrics, compared):
    if compared is None:
        text = "not_archived"
    else:
        text = (
            f"{compared['reproduction_status']} "
            f"ap_abs_diff={compared['ap_abs_diff']:.3e} "
            f"tp_match={compared['tp_match']} fp_match={compared['fp_match']} "
            f"tn_match={compared['tn_match']} fn_match={compared['fn_match']}"
        )
    print(
        f"{name} test_ap={json.dumps(metrics['average_precision'])} "
        f"TP={metrics['TP']} FP={metrics['FP']} compare={text}",
        flush=True,
    )


def main():
    expected_python = Path("/tmp/tl-research-venv/bin/python").resolve()
    if Path(sys.executable).resolve() != expected_python:
        raise SystemExit(f"Python must be {expected_python}, got {sys.executable}")
    if fw.HGB_PARAMS != EXPECTED_HGB:
        raise SystemExit(f"fw.fit_hgb parameters changed: {fw.HGB_PARAMS}")
    log("self_check")
    contract.self_check()
    log("load_bundle")
    started = time.perf_counter()
    saved_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        built = contract.load_bundle()
    finally:
        sys.stdout = saved_stdout
    feature_build_seconds = time.perf_counter() - started
    log(f"feature_build_seconds {feature_build_seconds:.3f}")
    population = contract.assert_population(
        built["y"], built["train"], built["select"], built["confirm"], built["test"],
    )
    built.pop("raw", None)
    gc.collect()

    log("merchant_encoding_audit")
    audit_core = contract.merchant_encoding_audit(built)
    own_check = own_label_gap(built)
    for key in (
        "train_own_label_gap_mean_abs",
        "train_fraud_own_label_gap_mean_abs",
        "train_own_label_gap_max_abs",
    ):
        if abs(own_check[key] - audit_core[key]) > 1e-12:
            raise SystemExit(f"own-label gap does not match merchant_encoding_audit: {key}")
    log("leakage_measurements")
    causal_rate, expanding_rate, leak = leakage_measurements(built)
    log("leakage_measurements done")

    specs = []

    started = time.perf_counter()
    rules = contract.rules_score(built)
    rules_seconds = time.perf_counter() - started
    unique = np.unique(rules[built["test"]])
    if not np.all(np.isin(unique, (0.0, 1.0))):
        raise SystemExit("prod_rules score is not binary")
    specs.append({
        "name": "prod_rules",
        "score": rules,
        "meta": {
            "fidelity": "TRUSTLEDGER_REPRODUCTION",
            "information_set": "production_rules",
            "weight_mode": None,
            "score_type": "binary",
            "trained": False,
            "columns": None,
            "timing": {
                "feature_seconds": 0.0,
                "fit_seconds": 0.0,
                "predict_seconds": rules_seconds,
            },
        },
    })

    def add_hgb(name, matrix, weight_mode, information_set, fidelity, feature_seconds, extra):
        log(f"fit {name}")
        full, fit_seconds, predict_seconds, infer_rows = fit_split_scores(matrix, built, weight_mode)
        log(f"fit {name} done train {fit_seconds:.3f}s predict {predict_seconds:.3f}s")
        meta = {
            "fidelity": fidelity,
            "information_set": information_set,
            "weight_mode": weight_mode,
            "score_type": "predicted_probability",
            "trained": True,
            "fit_rows": int(built["train"].sum()),
            "columns": int(matrix.shape[1]),
            "inference_rows": infer_rows,
            "hgb_params": dict(fw.HGB_PARAMS),
            "timing": {
                "feature_seconds": float(feature_seconds),
                "fit_seconds": fit_seconds,
                "predict_seconds": predict_seconds,
            },
        }
        meta.update(extra)
        specs.append({"name": name, "score": full, "meta": meta})
        del full

    started = time.perf_counter()
    pr14, _names = contract.pr14_matrix(built)
    pr14_seconds = time.perf_counter() - started
    add_hgb(
        "pr14_mapped_hgb", pr14, "balanced", "pr14_mapped",
        "TRUSTLEDGER_REPRODUCTION", pr14_seconds, {},
    )
    del pr14
    gc.collect()

    started = time.perf_counter()
    parity, _names, _enriched = contract.parity_parts(built)
    parity_seconds = time.perf_counter() - started
    add_hgb(
        "v2_enriched_sqrt", parity, "sqrt", "track_a_no_merchant_rate",
        "TRUSTLEDGER_REPRODUCTION", parity_seconds, {},
    )
    del parity
    gc.collect()

    started = time.perf_counter()
    merchant, _names = contract.merchant_matrix(built, built["merchant_rate"])
    merchant_seconds = time.perf_counter() - started
    add_hgb(
        "v2_merchant", merchant, "none", "original_frozen",
        "TRUSTLEDGER_REPRODUCTION", merchant_seconds,
        {"merchant_rate": "bundle merchant_rate from steps 0-119, including own and later train labels"},
    )
    del merchant
    gc.collect()

    started = time.perf_counter()
    causal_matrix, _names = contract.merchant_matrix(built, causal_rate)
    causal_matrix_seconds = time.perf_counter() - started
    add_hgb(
        "v2_merchant_step_causal", causal_matrix, "none", "step_causal",
        "LEAKAGE_VARIANT", leak["step_causal_seconds"] + causal_matrix_seconds,
        {
            "merchant_rate": "step_causal; test rows use only steps 0-119",
            "test_rate_source": "steps 0-119",
        },
    )
    del causal_matrix, causal_rate
    gc.collect()

    started = time.perf_counter()
    expanding_matrix, _names = contract.merchant_matrix(built, expanding_rate)
    expanding_matrix_seconds = time.perf_counter() - started
    add_hgb(
        "v2_merchant_expanding", expanding_matrix, "none", "expanding",
        "LEAKAGE_VARIANT", leak["expanding_seconds"] + expanding_matrix_seconds,
        {
            "merchant_rate": "expanding completed earlier steps",
            "distinct_information_set": True,
            "information_set_reason": (
                "Test rows can see labels from steps 120-149. "
                "This is not a substitute for the original_frozen reproduction."
            ),
        },
    )
    del expanding_matrix, expanding_rate
    gc.collect()

    preds = {}
    models = {}
    compared_by_name = {}
    for spec in specs:
        name = spec["name"]
        body, compared, pred = finish_model(name, spec["score"], built, spec["meta"])
        spec["score"] = None
        preds[name] = pred
        compared_by_name[name] = compared
        models[name] = {
            "fidelity": spec["meta"]["fidelity"],
            "information_set": spec["meta"]["information_set"],
            "weight_mode": spec["meta"]["weight_mode"],
            "score_type": spec["meta"]["score_type"],
            "timing": spec["meta"]["timing"],
            "reproduction_status": spec["meta"]["reproduction_status"],
            "test": body["test"],
            "select": body.get("select"),
            "confirm": body.get("confirm"),
            "amount_slices": spec["meta"]["amount_slices"],
            "category_breakdown": spec["meta"]["category_breakdown"],
        }
    del specs
    gc.collect()

    y_test = built["y"][built["test"]]
    overlaps = {
        "v2_merchant_vs_v2_merchant_step_causal": {
            "a": "v2_merchant",
            "b": "v2_merchant_step_causal",
            "population": "test fraud rows only",
            "alert_mask": "top 919 on each model",
            **fraud_overlap(y_test, preds["v2_merchant"], preds["v2_merchant_step_causal"]),
        },
        "v2_merchant_vs_v2_enriched_sqrt": {
            "a": "v2_merchant",
            "b": "v2_enriched_sqrt",
            "population": "test fraud rows only",
            "alert_mask": "top 919 on each model",
            **fraud_overlap(y_test, preds["v2_merchant"], preds["v2_enriched_sqrt"]),
        },
    }
    compare_reported = {name: compared_by_name[name] for name in ARCHIVED}
    if any(row is None for row in compare_reported.values()):
        raise SystemExit("archived model was missing from PREVIOUSLY_REPORTED")
    audit = {
        "population": {
            key: {"rows": int(value[0]), "fraud": int(value[1])}
            for key, value in population.items()
        },
        "merchant_encoding_audit": audit_core,
        "leakage_measurements": leak,
        "compare_reported": compare_reported,
        "models": models,
        "fraud_overlap_top919": overlaps,
        "timings": {"feature_build_seconds": feature_build_seconds},
        "peak_rss_bytes": peak_rss_bytes(),
        "peak_rss_unit": "bytes",
        "python": sys.version,
        "sklearn": __import__("sklearn").__version__,
        "numpy": np.__version__,
        "hgb_params": dict(fw.HGB_PARAMS),
        "models_deleted": True,
        "binaries_saved": False,
    }
    (ROOT / "audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )
    write_notes(audit)
    for path in ROOT.rglob("*"):
        if path.suffix in {".joblib", ".pkl", ".csv"}:
            raise SystemExit(f"refusing to leave {path}")
    for name in (
        "prod_rules", "pr14_mapped_hgb", "v2_enriched_sqrt",
        "v2_merchant", "v2_merchant_step_causal", "v2_merchant_expanding",
    ):
        compare_line(name, models[name]["test"], compared_by_name[name])


if __name__ == "__main__":
    main()
