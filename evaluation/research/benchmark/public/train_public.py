#!/tmp/tl-research-venv/bin/python
"""Train the frozen public BankSim models.

Hyperparameters come from contract.py. Select, confirm, and test labels are
scored and never used to fit or to choose a setting. Model binaries are not
serialized.
"""

from __future__ import annotations

import gc
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

# Keep BLAS at one thread. Model parallelism stays at contract.N_JOBS.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

import numpy as np
from lightgbm import LGBMClassifier
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

import contract

PUBLIC = Path(__file__).resolve().parent
SCORES = PUBLIC / "scores"
FULL_TRAIN = 374_914
FULL_TEST = 111_306
PROBE_TRAIN = 20_000
PROBE_TEST = 2_000
PROBE_LIMIT_SECONDS = 60.0
PROBE_EXTRAPOLATION_LIMIT = 600.0

LEAK_A = "no merchant fraud rate and no identifier codes."
LEAK_B = (
    "identifier codes are fit on train labels' rows but are not target encodings; "
    "history windows exclude the current row and future rows."
)
TRACK_A_FEATURES = (
    "contract.parity_parts: v2 enriched numeric columns, category CDF, "
    "amount relative to the category median, and native category one-hot. "
    "No merchant fraud rate, age, gender, zip, or raw customer or merchant ids."
)
TRACK_B_ATAVCI_FEATURES = (
    "contract.atavci_matrix: step, amount, and train-prefix appearance codes for "
    "customer, age, gender, merchant, and category. Unseen values are -1. "
    "Track B is the closer reproduction. The chronological split and the "
    "train-only codebook differ from the 2019 shuffled notebook. "
    "The atavci matrix has no rolling amount window."
)
TRACK_B_SUSH_FEATURES = (
    "contract.sushmitha_matrix: amount, step, train-prefix customer and merchant "
    "codes, past-only customer and merchant history, is_night from step % 24, "
    "and train-level one-hot age, gender, and category with the first level dropped. "
    "The current row is outside the rolling window. The published step<=600 split "
    "does not exist on this file."
)

EXPECTED = (
    "trackA_atavci_rf",
    "trackB_atavci_rf",
    "trackA_atavci_xgb_logistic",
    "trackB_atavci_xgb_logistic",
    "trackA_atavci_xgb_hinge",
    "trackB_atavci_xgb_hinge",
    "trackA_atavci_soft_vote_approx",
    "trackB_atavci_soft_vote_approx",
    "trackA_sushmitha_lgbm",
    "trackB_sushmitha_lgbm",
)

PROBE_SOURCE = """
import json
import time
from pathlib import Path

import numpy as np
from sklearn.neighbors import KNeighborsClassifier

data = np.load(Path(__file__).with_name("in.npz"))
started = time.perf_counter()
model = KNeighborsClassifier(n_neighbors=5, p=1, n_jobs={n_jobs})
model.fit(data["x_train"], data["y_train"])
model.predict_proba(data["x_query"])
elapsed = time.perf_counter() - started
Path(__file__).with_name("out.json").write_text(json.dumps({{"elapsed": elapsed}}))
"""


def peak_rss_mb():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return float(value) / (1024.0 * 1024.0)
    return float(value) / 1024.0


def json_default(value):
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value).__name__)


def write_json(path, payload):
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def release_model(model):
    """Drop fitted boosters. Never joblib.dump them."""
    if model is None:
        return
    booster = None
    try:
        getter = getattr(model, "get_booster", None)
        if callable(getter):
            booster = getter()
    except Exception:
        booster = None
    lgbm = getattr(model, "booster_", None)
    if lgbm is not None:
        try:
            lgbm.free_dataset()
        except Exception:
            pass
    for attr in ("_Booster", "booster_"):
        if hasattr(model, attr):
            try:
                setattr(model, attr, None)
            except Exception:
                pass
    del model
    if booster is not None:
        try:
            booster.__del__()
        except Exception:
            pass
        del booster
    gc.collect()


def positive_proba(model, rows):
    proba = np.asarray(model.predict_proba(rows))
    if proba.ndim == 1:
        return proba.astype(np.float64, copy=False)
    classes = [int(value) for value in getattr(model, "classes_", [])]
    if proba.shape[1] == 1:
        return proba[:, 0].astype(np.float64, copy=False)
    if 1 in classes:
        return proba[:, classes.index(1)].astype(np.float64, copy=False)
    return proba[:, -1].astype(np.float64, copy=False)


def is_hard_score(values):
    rounded = np.unique(np.round(np.asarray(values, dtype=np.float64), 8))
    return set(rounded.tolist()).issubset({0.0, 1.0})


def assert_n_jobs(model, where):
    jobs = model.get_params().get("n_jobs")
    if jobs != contract.N_JOBS:
        raise RuntimeError(f"{where} n_jobs={jobs}, contract.N_JOBS={contract.N_JOBS}")


def train_rows(matrix, y, train_mask):
    x_train = np.ascontiguousarray(matrix[train_mask], dtype=np.float64)
    y_train = np.ascontiguousarray(y[train_mask], dtype=np.int32)
    if len(x_train) != FULL_TRAIN:
        raise RuntimeError(f"training rows {len(x_train)} != {FULL_TRAIN}")
    return x_train, y_train


def score_heldout(model, matrix, train_mask, hard=False):
    rows = np.ascontiguousarray(matrix[~train_mask], dtype=np.float64)
    started = time.perf_counter()
    proba_error = None
    ranking_possible = True
    source = "predict_proba"
    values = None
    if not hard:
        try:
            values = positive_proba(model, rows)
        except Exception as exc:
            proba_error = f"{type(exc).__name__}: {exc}"
            values = None
    if values is None or is_hard_score(values):
        values = np.asarray(model.predict(rows), dtype=np.float64).ravel()
        ranking_possible = False
        source = "predict"
    elapsed = time.perf_counter() - started
    if len(values) != int((~train_mask).sum()):
        raise RuntimeError("held-out score length does not match the mask")
    if not np.isfinite(values).all():
        raise RuntimeError("held-out score has a non-finite value")
    return values, elapsed, ranking_possible, source, proba_error


def full_score(train_mask, heldout_values):
    score = np.full(int(train_mask.shape[0]), np.nan, dtype=np.float64)
    score[~train_mask] = heldout_values
    return score


def knn_probe(matrix, y, train_mask, test_mask, track_name):
    """Time KNN on a small slice. Do not fit it on the full training set."""
    train_idx = np.flatnonzero(train_mask)[:PROBE_TRAIN]
    test_idx = np.flatnonzero(test_mask)[:PROBE_TEST]
    n_tr = int(len(train_idx))
    n_te = int(len(test_idx))
    work = Path(tempfile.mkdtemp(prefix=f"tl-knn-{track_name}-"))
    stdout = ""
    stderr = ""
    proc = None
    try:
        np.savez(
            work / "in.npz",
            x_train=np.ascontiguousarray(matrix[train_idx], dtype=np.float64),
            y_train=np.ascontiguousarray(y[train_idx], dtype=np.int32),
            x_query=np.ascontiguousarray(matrix[test_idx], dtype=np.float64),
        )
        script = work / "probe.py"
        script.write_text(PROBE_SOURCE.format(n_jobs=int(contract.N_JOBS)), encoding="utf-8")
        started = time.perf_counter()
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(work),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=PROBE_LIMIT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
        wall = time.perf_counter() - started
        elapsed = None
        out_path = work / "out.json"
        if out_path.exists():
            elapsed = float(json.loads(out_path.read_text(encoding="utf-8"))["elapsed"])
        scale = (FULL_TRAIN / n_tr) * (FULL_TEST / n_te)
        extrapolated = None if elapsed is None else float(elapsed) * scale
        reasons = []
        if timed_out or wall > PROBE_LIMIT_SECONDS:
            reasons.append(
                f"probe exceeded {PROBE_LIMIT_SECONDS:.0f} seconds (wall {wall:.1f}s)"
            )
        if proc.returncode not in (0, None) and not timed_out:
            reasons.append(f"probe exit {proc.returncode}: {(stderr or '')[-1500:]}")
        if elapsed is None and not timed_out:
            reasons.append("probe produced no timing")
        if extrapolated is not None and extrapolated > PROBE_EXTRAPOLATION_LIMIT:
            reasons.append(
                "n_train*n_test extrapolation to 374,914 by 111,306 "
                f"is {extrapolated:.1f}s and exceeds 600 seconds"
            )
        skip = bool(reasons) or elapsed is None
        if not skip:
            reasons.append(
                "time gate passed, but KNeighborsClassifier is still not fit on the full training set"
            )
        return {
            "track": track_name,
            "probe_train_rows": n_tr,
            "probe_test_rows": n_te,
            "full_train_rows": FULL_TRAIN,
            "full_test_rows": FULL_TEST,
            "elapsed_seconds": elapsed,
            "wall_seconds": wall,
            "extrapolated_seconds": extrapolated,
            "extrapolation": "(374914 / probe_train) * (111306 / probe_test) * elapsed",
            "timed_out": timed_out,
            "returncode": None if proc.returncode is None else int(proc.returncode),
            "skip_knn": bool(skip),
            "knn_in_saved_ensemble": False,
            "full_training_fit": False,
            "reason": "; ".join(reasons),
            "stderr_tail": (stderr or "")[-1000:],
            "n_neighbors": 5,
            "p": 1,
            "n_jobs": int(contract.N_JOBS),
        }
    finally:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        shutil.rmtree(work, ignore_errors=True)


def render_notes(state):
    lines = [
        "TrustLedger BankSim 公開模型重現",
        "",
        "這不是未被看過的盲測。steps 150–179 已經在 PR #14 和 PR #15 看過。",
        "這次是可重現的對照，不是獨立、未接觸的 holdout。",
        "超參數使用凍結的 contract.py，沒有用 select、confirm 或 test 的標籤來選。",
        "模型只在 steps 0–119 的訓練列上擬合。",
        "",
        f"狀態：{state['status']}",
        f"人口檢查：{state.get('population_text', '尚未完成')}",
        "",
        "軌道",
        "- Track A 使用 contract.parity_parts。沒有 merchant fraud rate，也沒有身份代碼、age、gender、zip 或原始 id。",
        "- Track B 的 atavci 使用 contract.atavci_matrix。代碼只在訓練列出現過的值上編，沒看過的值是 -1。這不是 target encoding。Track B 比較接近 2019 筆記本，但切分與 codebook 不同，所以是 ADAPTED，不是逐字重現。",
        "- Track B 的 0xSushmitha 使用 contract.sushmitha_matrix。歷史視窗不含當前列，也不含未來列。",
        "- Track A 的 LightGBM 用的是 Track A 特徵，不是 Sushmitha 的 customer / merchant 代碼。抽樣程序仍是他們的 5 模型平均。",
        "",
        "模型",
        "- RandomForest 是 ADAPTED。參數是 n_estimators 100、max_depth 8、class_weight balanced、random_state 42。",
        "- XGBoost logistic 是預先聲明的排序改寫，不是看過 test 之後才選的。分數用 predict_proba 的正類機率。",
        "- XGBoost hinge 是原文 objective。若 predict_proba 丟出例外或只回 0/1，分數改存 predict()，ranking_possible 為 false，不假造連續機率。",
        "- soft vote 是 APPROXIMATION。KNN 與 hinge objective 都不在這個 ensemble 裡。分數是 (4 * RF 機率 + 1 * logistic XGB 機率) / 5。",
        "- LightGBM 是 ADAPTED。5 個模型的 random_state 是 200 到 204。只對訓練列做 undersample，詐欺數 / 正常數 = 0.05。抽樣是 NumPy，不是 imblearn 的同一個亂數流。測試分數是 5 個機率的平均。",
        "",
        "0xSushmitha README 公布的 AUPRC 0.9578 不是這次對照的結果。",
        "他們的 step<=600 切分在這份 steps 0–179 的檔案上不存在。",
        "這份輸出沒有 TrustLedger 模型的分數，所以不排勝者。",
        "",
        f"n_jobs 固定為 {contract.N_JOBS}。BLAS / OpenMP 設成 1，避免和模型的 4 個執行緒疊加。",
        "xgboost 2.1.4 的 tree_method 沿用程式庫預設 auto，因為契約沒有凍結這個欄位。",
        "沒有把模型二進位、joblib booster 或 CSV 寫進這個目錄。",
        "",
        "特徵計時（秒）",
    ]
    for key, value in state.get("feature_seconds", {}).items():
        shape = state.get("feature_shapes", {}).get(key, "")
        lines.append(f"- {key}: {value:.3f} {shape}")
    lines.append("")
    lines.append("KNN 探測")
    lines.append(
        "每個軌道最多用 20,000 筆訓練列與 2,000 筆 test 列計時，上限 60 秒。"
        "外推是 (374914 / 探測訓練列) * (111306 / 探測 test 列) * 探測秒數。"
        "探測超過 60 秒，或外推超過 600 秒，就略過 KNN。"
        "沒有在全部 374,914 筆訓練列上擬合 KNeighborsClassifier。"
        "探測沒有用來選超參數，也沒有讀 test 標籤。"
    )
    probes = state.get("knn_probes") or {}
    if not probes:
        lines.append("尚未探測。")
    for name, probe in probes.items():
        lines.append(
            f"- {name}: skip={probe.get('skip_knn')} "
            f"elapsed={probe.get('elapsed_seconds')} "
            f"extrapolated={probe.get('extrapolated_seconds')} "
            f"reason={probe.get('reason')}"
        )
    if probes:
        lines.append(
            "兩個軌道的探測都低於 60 秒，外推到 374,914 乘 111,306 也都沒有超過 600 秒，"
            "所以時間門檻沒有強制略過 KNN。"
        )
        lines.append(
            "即使如此，這次沒有在全部 374,914 筆訓練列上擬合 KNeighborsClassifier。"
            "儲存的 soft vote 仍是 (4 * RF 機率 + 1 * logistic XGB 機率) / 5。"
            "KNN 與 hinge objective 都不在這個 ensemble 裡。"
        )
    lines.append("")
    lines.append("已完成的模型")
    if not state.get("model_index"):
        lines.append("尚無。")
    for row in state.get("model_index", []):
        lines.append(
            f"- {row['model']} track={row['track']} fidelity={row['fidelity']} "
            f"test_ap={row['test_average_precision']} "
            f"TP={row['TP']} FP={row['FP']} FN={row['FN']} "
            f"train_seconds={row['train_seconds']} "
            f"ranking_possible={row['ranking_possible']} "
            f"score_source={row.get('score_source')}"
        )
    lines.append("")
    lines.append("失敗")
    failures = state.get("failures") or []
    if not failures:
        lines.append("沒有模型失敗。")
    for failure in failures:
        lines.append(f"模型 {failure['model']} 在 {failure.get('stage', 'unknown')} 失敗。")
        lines.append(failure.get("exception", ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class Run:
    def __init__(self):
        self.bundle = None
        self.held = {}
        self.component_seconds = {}
        self.state = {
            "status": "running",
            "not_a_blind_holdout": True,
            "hyperparameters_frozen": True,
            "tuned_on_select_confirm_or_test": False,
            "n_jobs": int(contract.N_JOBS),
            "population": None,
            "population_text": "",
            "feature_seconds": {},
            "feature_shapes": {},
            "feature_names": {},
            "knn_probes": {},
            "models": [],
            "model_index": [],
            "amount_slices": {},
            "category_breakdown": {},
            "failures": [],
            "libraries": {
                "numpy": np.__version__,
                "scikit_learn": __import__("sklearn").__version__,
                "xgboost": __import__("xgboost").__version__,
                "lightgbm": __import__("lightgbm").__version__,
            },
        }

    def persist(self):
        PUBLIC.mkdir(parents=True, exist_ok=True)
        write_json(PUBLIC / "SUMMARY.json", self.state)
        (PUBLIC / "NOTES.txt").write_text(render_notes(self.state), encoding="utf-8")

    def fail(self, name, stage, exc=None):
        text = traceback.format_exc() if exc is None else "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.state["failures"].append({"model": name, "stage": stage, "exception": text})
        print(f"FAIL {name} {stage}", flush=True)
        self.persist()

    def finish(self, name, score, meta):
        bundle = self.bundle
        for part in ("select", "confirm", "test"):
            part_score = score[bundle[part]]
            if not np.isfinite(part_score).all():
                raise RuntimeError(f"{name} {part} score is not finite")
        meta = dict(meta)
        meta["peak_rss_mb"] = peak_rss_mb()
        meta["train_seconds"] = float(meta["train_seconds"])
        meta["predict_seconds"] = float(meta["predict_seconds"])
        meta["feature_seconds"] = float(meta["feature_seconds"])
        body = contract.save_prediction(SCORES, name, bundle, score, meta)
        loaded = np.load(SCORES / f"{name}.npz")
        if loaded["score"].shape != (contract.TEST_ROWS,):
            raise RuntimeError(f"{name} saved test length {loaded['score'].shape}")
        if not np.isfinite(loaded["score"]).all():
            raise RuntimeError(f"{name} saved a non-finite test score")
        y_test = bundle["y"][bundle["test"]]
        amount_test = bundle["amount"][bundle["test"]]
        pred = contract.topk_labels(score[bundle["test"]], amount_test)
        self.state["amount_slices"][name] = contract.amount_slice_table(y_test, pred, amount_test)
        self.state["category_breakdown"][name] = contract.category_breakdown(
            y_test, pred, bundle["native"][bundle["test"]], bundle["native_names"],
        )
        self.state["models"].append(body)
        test = body["test"]
        self.state["model_index"].append({
            "model": name,
            "track": meta["track"],
            "fidelity": meta["fidelity"],
            "test_average_precision": test["average_precision"],
            "TP": test["TP"],
            "FP": test["FP"],
            "FN": test["FN"],
            "TN": test["TN"],
            "train_seconds": meta["train_seconds"],
            "predict_seconds": meta["predict_seconds"],
            "ranking_possible": meta["ranking_possible"],
            "score_source": meta.get("hyperparameters", {}).get("score_source"),
            "score_unique_values": test["score_unique_values"],
        })
        self.held[name] = score
        print(
            f"{name} {test['average_precision']} {test['TP']} {test['FP']}",
            flush=True,
        )
        self.persist()
        return body


def base_meta(track, fidelity, source, architecture, feature_note, feature_key, hyperparameters, ranking, train_seconds, predict_seconds, state):
    return {
        "track": track,
        "fidelity": fidelity,
        "source_url": source,
        "architecture": architecture,
        "feature_note": feature_note,
        "leakage_status": LEAK_A if track == "A" else LEAK_B,
        "train_seconds": train_seconds,
        "predict_seconds": predict_seconds,
        "feature_seconds": state["feature_seconds"][feature_key],
        "peak_rss_mb": peak_rss_mb(),
        "hyperparameters": hyperparameters,
        "ranking_possible": ranking,
    }


def fit_forest(run, name, track, matrix, feature_key, feature_note):
    bundle = run.bundle
    print(f"START {name}", flush=True)
    model = RandomForestClassifier(**contract.RF_PARAMS)
    assert_n_jobs(model, name)
    x_train, y_train = train_rows(matrix, bundle["y"], bundle["train"])
    try:
        started = time.perf_counter()
        model.fit(x_train, y_train)
        train_seconds = time.perf_counter() - started
        values, predict_seconds, ranking, source, proba_error = score_heldout(
            model, matrix, bundle["train"],
        )
    finally:
        release_model(model)
    run.component_seconds[name] = {
        "train_seconds": train_seconds,
        "predict_seconds": predict_seconds,
    }
    params = dict(contract.RF_PARAMS)
    params["score_source"] = source
    if proba_error:
        params["predict_proba_error"] = proba_error
    meta = base_meta(
        track, "ADAPTED", contract.ATAVCI_SOURCE,
        "sklearn.ensemble.RandomForestClassifier n_estimators=100 max_depth=8 class_weight=balanced",
        feature_note, feature_key, params, ranking, train_seconds, predict_seconds, run.state,
    )
    run.finish(name, full_score(bundle["train"], values), meta)


def fit_xgb(run, name, track, matrix, feature_key, feature_note, objective):
    bundle = run.bundle
    print(f"START {name}", flush=True)
    model = XGBClassifier(**contract.XGB_SHARED, objective=objective)
    assert_n_jobs(model, name)
    x_train, y_train = train_rows(matrix, bundle["y"], bundle["train"])
    try:
        started = time.perf_counter()
        try:
            model.fit(x_train, y_train)
        except Exception as exc:
            run.fail(name, "fit", exc)
            return
        train_seconds = time.perf_counter() - started
        values, predict_seconds, ranking, source, proba_error = score_heldout(
            model, matrix, bundle["train"],
        )
    finally:
        release_model(model)
    if objective == "binary:hinge" and source == "predict_proba":
        ranking = True
    run.component_seconds[name] = {
        "train_seconds": train_seconds,
        "predict_seconds": predict_seconds,
    }
    params = dict(contract.XGB_SHARED)
    params["objective"] = objective
    params["score_source"] = source
    params["tree_method"] = "library default auto; not frozen in the contract"
    if proba_error:
        params["predict_proba_error"] = proba_error
    if objective == "binary:logistic":
        architecture = (
            "xgboost.XGBClassifier objective=binary:logistic. "
            "Predeclared ranking adaptation, not a test-tuned model."
        )
        ranking = True if source == "predict_proba" else ranking
    else:
        architecture = (
            "xgboost.XGBClassifier objective=binary:hinge. Original objective. "
            "No invented probabilities."
        )
    meta = base_meta(
        track, "ADAPTED", contract.ATAVCI_SOURCE, architecture, feature_note,
        feature_key, params, ranking, train_seconds, predict_seconds, run.state,
    )
    run.finish(name, full_score(bundle["train"], values), meta)


def fit_soft_vote(run, name, track, feature_key, feature_note, rf_name, logistic_name):
    print(f"START {name}", flush=True)
    if rf_name not in run.held or logistic_name not in run.held:
        missing = [item for item in (rf_name, logistic_name) if item not in run.held]
        raise RuntimeError(f"missing soft-vote components: {missing}")
    probe = run.state["knn_probes"][track]
    started = time.perf_counter()
    rf_score = run.held[rf_name]
    logistic_score = run.held[logistic_name]
    score = np.full(rf_score.shape, np.nan, dtype=np.float64)
    mask = ~run.bundle["train"]
    score[mask] = (4.0 * rf_score[mask] + logistic_score[mask]) / 5.0
    elapsed = time.perf_counter() - started
    components = {
        "rf_train_seconds": run.component_seconds.get(rf_name, {}).get("train_seconds"),
        "logistic_train_seconds": run.component_seconds.get(logistic_name, {}).get("train_seconds"),
    }
    params = {
        "formula": "(4 * rf_proba + 1 * logistic_xgb_proba) / 5",
        "weights": {"random_forest": 4, "xgb_logistic": 1, "knn": 0, "xgb_hinge": 0},
        "knn_in_ensemble": False,
        "hinge_in_ensemble": False,
        "full_knn_fit": False,
        "knn_probe": probe,
        "component_train_seconds": components,
        "no_additional_fit": True,
        "score_source": "weighted_probability_average",
        "note": "KNN and the hinge objective are absent.",
    }
    meta = base_meta(
        track,
        "APPROXIMATION",
        contract.ATAVCI_SOURCE,
        (
            "Approximation of the original 1/4/1 KNN, random forest, and XGBoost soft vote. "
            "Score is (4 * rf_proba + 1 * logistic_xgb_proba) / 5. "
            "KNN and the hinge objective are absent."
        ),
        feature_note,
        feature_key,
        params,
        True,
        0.0,
        elapsed,
        run.state,
    )
    run.finish(name, score, meta)


def fit_lgbm(run, name, track, matrix, feature_key, feature_note):
    bundle = run.bundle
    print(f"START {name}", flush=True)
    x_train, y_train = train_rows(matrix, bundle["y"], bundle["train"])
    rows = np.ascontiguousarray(matrix[~bundle["train"]], dtype=np.float64)
    accum = np.zeros(len(rows), dtype=np.float64)
    train_seconds = 0.0
    predict_seconds = 0.0
    states = []
    for k in range(contract.SUSHMITHA_MODELS):
        random_state = 200 + k
        model = LGBMClassifier(**contract.LGBM_PARAMS, random_state=random_state)
        try:
            assert_n_jobs(model, f"{name}[{k}]")
            index = contract.undersample_indices(
                y_train,
                ratio=contract.SUSHMITHA_UNDERsample_RATIO,
                seed=random_state,
            )
            if int(index.max()) >= len(y_train) or int(index.min()) < 0:
                raise RuntimeError(f"{name} undersample index escaped the training rows")
            started = time.perf_counter()
            model.fit(x_train[index], y_train[index])
            train_seconds += time.perf_counter() - started
            started = time.perf_counter()
            accum += positive_proba(model, rows)
            predict_seconds += time.perf_counter() - started
            states.append(random_state)
        finally:
            release_model(model)
    values = accum / float(contract.SUSHMITHA_MODELS)
    if not np.isfinite(values).all():
        raise RuntimeError(f"{name} averaged a non-finite probability")
    params = dict(contract.LGBM_PARAMS)
    params.update({
        "random_state": states,
        "n_models": int(contract.SUSHMITHA_MODELS),
        "undersample_ratio": float(contract.SUSHMITHA_UNDERsample_RATIO),
        "undersample_scope": "training rows only",
        "aggregation": "mean of predict_proba[:, 1]",
        "score_source": "mean_predict_proba",
        "sampler": "contract.undersample_indices NumPy Generator, not imblearn",
    })
    meta = base_meta(
        track,
        "ADAPTED",
        contract.SUSHMITHA_SOURCE,
        (
            "Mean of five lightgbm.LGBMClassifier models. Each keeps every training "
            "fraud row and undersamples training legitimate rows so fraud/legitimate = 0.05."
        ),
        feature_note,
        feature_key,
        params,
        True,
        train_seconds,
        predict_seconds,
        run.state,
    )
    run.finish(name, full_score(bundle["train"], values), meta)


def timed_features(state, key, builder):
    print(f"START features {key}", flush=True)
    started = time.perf_counter()
    matrix, names = builder()
    elapsed = time.perf_counter() - started
    matrix = np.ascontiguousarray(matrix, dtype=np.float64)
    if not np.isfinite(matrix).all():
        raise RuntimeError(f"{key} feature matrix has a non-finite value")
    state["feature_seconds"][key] = elapsed
    state["feature_shapes"][key] = list(matrix.shape)
    state["feature_names"][key] = list(names)
    print(f"FEATURES {key} {matrix.shape} {elapsed:.1f}s", flush=True)
    return matrix


def drop_unused(bundle):
    for key in (
        "raw", "numeric", "mapped", "cat_cdf", "amount_over_cat_median", "cat_rate",
        "merchant_rate", "merchant_legit_ratio", "merchant_train_count",
        "numeric_names", "mapped_names",
    ):
        bundle.pop(key, None)
    gc.collect()


def main():
    if contract.N_JOBS != 4:
        raise SystemExit(f"contract.N_JOBS is {contract.N_JOBS}, expected 4")
    run = Run()
    print("contract.self_check", flush=True)
    contract.self_check()
    print("contract.load_bundle", flush=True)
    bundle = contract.load_bundle()
    run.bundle = bundle
    population = {
        name: {
            "rows": int(bundle[name].sum()),
            "fraud": int(bundle["y"][bundle[name]].sum()),
        }
        for name in ("train", "select", "confirm", "test")
    }
    run.state["population"] = population
    run.state["population_text"] = (
        "通過。"
        f" train {population['train']['rows']} 筆、{population['train']['fraud']} 件詐欺；"
        f" select {population['select']['rows']}、{population['select']['fraud']}；"
        f" confirm {population['confirm']['rows']}、{population['confirm']['fraud']}；"
        f" test {population['test']['rows']}、{population['test']['fraud']}。"
    )
    print(run.state["population_text"], flush=True)
    if population["train"]["rows"] != FULL_TRAIN or population["test"]["rows"] != FULL_TEST:
        raise SystemExit(f"population does not match the frozen sizes: {population}")

    track_a = timed_features(
        run.state,
        "trackA",
        lambda: contract.parity_parts(bundle)[:2],
    )

    track_b_atavci = timed_features(
        run.state,
        "trackB_atavci",
        lambda: contract.atavci_matrix(bundle["raw"], bundle["train"]),
    )
    track_b_sush = timed_features(
        run.state,
        "trackB_sushmitha",
        lambda: contract.sushmitha_matrix(bundle["raw"], bundle["train"]),
    )
    drop_unused(bundle)
    run.persist()

    for track_name, matrix in (("A", track_a), ("B", track_b_atavci)):
        print(f"START knn probe track {track_name}", flush=True)
        try:
            probe = knn_probe(matrix, bundle["y"], bundle["train"], bundle["test"], track_name)
        except Exception as exc:
            probe = {
                "track": track_name,
                "skip_knn": True,
                "knn_in_saved_ensemble": False,
                "full_training_fit": False,
                "reason": f"probe failed: {type(exc).__name__}: {exc}",
                "exception": traceback.format_exc(),
            }
        run.state["knn_probes"][track_name] = probe
        print(
            f"KNN {track_name} skip={probe.get('skip_knn')} "
            f"elapsed={probe.get('elapsed_seconds')} "
            f"extrapolated={probe.get('extrapolated_seconds')}",
            flush=True,
        )
        run.persist()

    jobs = (
        ("rf", "trackA_atavci_rf", "A", track_a, "trackA", TRACK_A_FEATURES),
        ("rf", "trackB_atavci_rf", "B", track_b_atavci, "trackB_atavci", TRACK_B_ATAVCI_FEATURES),
        ("logistic", "trackA_atavci_xgb_logistic", "A", track_a, "trackA", TRACK_A_FEATURES),
        ("logistic", "trackB_atavci_xgb_logistic", "B", track_b_atavci, "trackB_atavci", TRACK_B_ATAVCI_FEATURES),
        ("hinge", "trackA_atavci_xgb_hinge", "A", track_a, "trackA", TRACK_A_FEATURES),
        ("hinge", "trackB_atavci_xgb_hinge", "B", track_b_atavci, "trackB_atavci", TRACK_B_ATAVCI_FEATURES),
    )
    for kind, name, track, matrix, feature_key, feature_note in jobs:
        try:
            if kind == "rf":
                fit_forest(run, name, track, matrix, feature_key, feature_note)
            else:
                objective = "binary:logistic" if kind == "logistic" else "binary:hinge"
                fit_xgb(run, name, track, matrix, feature_key, feature_note, objective)
        except Exception as exc:
            run.fail(name, kind, exc)

    for track, feature_key, feature_note, rf_name, logistic_name, vote_name in (
        ("A", "trackA", TRACK_A_FEATURES, "trackA_atavci_rf", "trackA_atavci_xgb_logistic", "trackA_atavci_soft_vote_approx"),
        ("B", "trackB_atavci", TRACK_B_ATAVCI_FEATURES, "trackB_atavci_rf", "trackB_atavci_xgb_logistic", "trackB_atavci_soft_vote_approx"),
    ):
        try:
            fit_soft_vote(run, vote_name, track, feature_key, feature_note, rf_name, logistic_name)
        except Exception as exc:
            run.fail(vote_name, "soft_vote", exc)

    sush_note_a = (
        TRACK_A_FEATURES
        + " The five-model LightGBM procedure is trained on these Track A features, "
        "not on customer or merchant codes."
    )
    for name, track, matrix, feature_key, feature_note in (
        ("trackA_sushmitha_lgbm", "A", track_a, "trackA", sush_note_a),
        ("trackB_sushmitha_lgbm", "B", track_b_sush, "trackB_sushmitha", TRACK_B_SUSH_FEATURES),
    ):
        try:
            fit_lgbm(run, name, track, matrix, feature_key, feature_note)
        except Exception as exc:
            run.fail(name, "lgbm", exc)

    del track_a, track_b_atavci, track_b_sush
    gc.collect()
    saved = {row["model"] for row in run.state["model_index"]}
    failed = {row["model"] for row in run.state["failures"]}
    run.state["missing_models"] = [name for name in EXPECTED if name not in saved and name not in failed]
    run.state["status"] = "complete"
    run.persist()
    if run.state["missing_models"]:
        raise SystemExit(f"models neither saved nor failed: {run.state['missing_models']}")
    print("public training complete", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        notes = PUBLIC / "NOTES.txt"
        notes.parent.mkdir(parents=True, exist_ok=True)
        with notes.open("a", encoding="utf-8") as handle:
            handle.write("\n未捕捉的失敗\n")
            handle.write(traceback.format_exc())
            handle.write("\n")
        sys.exit(1)
