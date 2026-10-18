"""Cut one chronological BankSim holdout for the quick TrustLedger evaluation.

The raw CSV stays outside the repository. This script writes a derived JSONL
under /tmp and a summary JSON that contains no customer or merchant ids.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 20261017
SOURCE = Path(os.environ.get("BANKSIM_CSV", "/tmp/tl-eval-data/banks.csv"))
OUT_DIR = Path(os.environ.get("QUICK_EVAL_DIR", "/tmp/tl-eval-data/quick"))
SUMMARY_PATH = Path(__file__).resolve().parent / "results" / "sample_summary.json"
BASE = datetime(2014, 1, 1, tzinfo=timezone.utc)
CATEGORY_MAP = {
    "es_barsandrestaurants": "dining",
    "es_food": "groceries",
    "es_hyper": "groceries",
    "es_transportation": "transportation",
    "es_tech": "electronics",
}


def choose_suffix(step_counts: Counter) -> tuple[int, int, int]:
    """Latest whole steps whose row count is in [5000, 15000], closest to 10000."""
    steps = sorted(step_counts)
    best: tuple[int, int, int, int, int] | None = None
    for index, start in enumerate(steps):
        total = sum(step_counts[step] for step in steps[index:])
        if 5000 <= total <= 15000:
            candidate = (abs(total - 10000), -start, start, steps[-1], total)
            if best is None or candidate < best:
                best = candidate
    if best is None:
        raise SystemExit("No chronological suffix fell inside 5,000–15,000 rows.")
    return best[2], best[3], best[4]


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"Missing BankSim file: {SOURCE}")
    step_counts: Counter = Counter()
    fraud_counts: Counter = Counter()
    bad_labels: Counter = Counter()
    total = 0
    with SOURCE.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        expected = [
            "step", "customer", "age", "gender", "zipcodeOri", "merchant",
            "zipMerchant", "category", "amount", "fraud",
        ]
        if [cell.strip() for cell in header] != expected:
            raise SystemExit(f"Unexpected header: {header}")
        for row in reader:
            total += 1
            row = [cell.strip().strip("'") for cell in row]
            if len(row) != 10:
                raise SystemExit(f"Short row at data index {total - 1}")
            label = row[9]
            if label not in {"0", "1"}:
                bad_labels[label] += 1
                continue
            step_counts[int(row[0])] += 1
            fraud_counts[int(label)] += 1
    if bad_labels:
        raise SystemExit(f"Fraud labels were not only 0/1: {bad_labels}")
    start, end, eval_rows = choose_suffix(step_counts)

    eval_customers: set[str] = set()
    held: dict[tuple[str, int], list[tuple[int, list[str]]]] = defaultdict(list)
    eval_categories: Counter = Counter()
    other_categories: Counter = Counter()
    fraud_by_category: Counter = Counter()
    amount_band: Counter = Counter()
    eval_fraud = 0
    with SOURCE.open(newline="") as handle:
        reader = csv.reader(handle)
        next(reader)
        for index, row in enumerate(reader):
            row = [cell.strip().strip("'") for cell in row]
            step = int(row[0])
            if step < start - 1:
                continue
            customer = row[1]
            if step >= start:
                eval_customers.add(customer)
            held[(customer, step)].append((index, row))
    history_rows = 0
    history_customers: set[str] = set()
    records: list[dict] = []
    for (customer, step), items in held.items():
        if customer not in eval_customers:
            continue
        token = "acct_" + hashlib.sha256(customer.encode()).hexdigest()[:16]
        for offset, (index, row) in enumerate(items):
            label = int(row[9])
            source_category = row[7]
            mapped = CATEGORY_MAP.get(source_category, "other")
            split = "eval" if step >= start else "history"
            if split == "history":
                history_rows += 1
                history_customers.add(customer)
            else:
                eval_categories[source_category] += 1
                if mapped == "other":
                    other_categories[source_category] += 1
                fraud_by_category[source_category] += label
                amount_band[(label, float(row[8]) >= 250)] += 1
                eval_fraud += label
            records.append({
                "split": split,
                "fraud": label,
                "step": step,
                "row_index": index,
                "source_category": source_category,
                "transaction": {
                    "id": f"txn_{step}_{index}",
                    "occurred_at": (BASE + timedelta(days=step, seconds=offset)).isoformat(),
                    "amount": float(row[8]),
                    "currency": "USD",
                    "direction": "debit",
                    "merchant_display": row[5][:80],
                    "merchant_category": mapped,
                    "source": "synthetic",
                    "account_token": token,
                    "is_subscription": False,
                },
            })
    records.sort(key=lambda item: (
        item["transaction"]["account_token"],
        item["transaction"]["occurred_at"],
        item["row_index"],
    ))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jsonl = OUT_DIR / "quick_sample.jsonl"
    with jsonl.open("w") as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    normal = eval_rows - eval_fraud
    summary = {
        "dataset_name": "BankSim (Lopez-Rojas & Axelsson, EMSS 2014)",
        "source_file_basename": SOURCE.name,
        "license_note": "CC BY-NC-SA 4.0. Do not commit or redistribute the raw CSV.",
        "sparkov_status": (
            "Official Kaggle Sparkov was not downloaded (no Kaggle credentials used). "
            "The local Hugging Face fraudTrain.csv is a truncated Excel export with "
            "scientific-notation card numbers, so it was not used."
        ),
        "original_row_count": total,
        "original_fraud_count": fraud_counts[1],
        "original_normal_count": fraud_counts[0],
        "original_prevalence": fraud_counts[1] / total,
        "eval_row_count": eval_rows,
        "eval_fraud_count": eval_fraud,
        "eval_normal_count": normal,
        "eval_prevalence": eval_fraud / eval_rows,
        "eval_customer_count": len(eval_customers),
        "history_row_count": history_rows,
        "history_customer_count": len(history_customers),
        "history_scope": (
            "Only the previous step is exported. Older rows are outside the 24 hour "
            "window the authoritative duplicate rule can use, and is_subscription is "
            "false so older subscription history cannot change a decision."
        ),
        "step_min_eval": start,
        "step_max_eval": end,
        "time_range_utc": {
            "start": (BASE + timedelta(days=start)).isoformat(),
            "end_nominal": (BASE + timedelta(days=end, hours=23, minutes=59)).isoformat(),
            "clock": "imputed; intra-day seconds are file order within customer and step, not a real clock",
        },
        "sampling_method": (
            "Contiguous suffix of whole steps, natural prevalence, closest to 10000 "
            "rows inside 5000-15000. Not a random row sample and not fraud-enriched."
        ),
        "seed": SEED,
        "category_map": CATEGORY_MAP,
        "eval_source_category_counts": dict(eval_categories.most_common()),
        "unsupported_categories": [
            {"source_category": name, "eval_count": count}
            for name, count in other_categories.most_common()
        ],
        "eval_fraud_by_source_category": {
            name: fraud_by_category[name] for name in eval_categories
        },
        "amount_ge_250_by_fraud": {
            f"fraud_{label}_ge250_{int(flag)}": count
            for (label, flag), count in sorted(amount_band.items())
        },
        "assumptions": [
            "currency USD is a schema requirement; BankSim publishes no currency code.",
            "direction debit is assumed; BankSim publishes no credit/debit field.",
            "is_subscription is false for every row; subscription flags were not invented.",
            "source synthetic is the schema tag for this offline sample, not the product fixture.",
            "One step is treated as one day starting 2014-01-01 UTC. The hour is not in the data.",
            "Customer ids are hashed into account_token and are absent from this summary.",
        ],
        "not_evaluable": [
            "duplicate rule-specific accuracy: no independent duplicate labels",
            "amount_anomaly rule-specific accuracy: no independent amount-anomaly labels",
            "subscription_change: no subscription flag, price history, or subscription labels",
        ],
        "fraud_label_check": "Every fraud field parsed as the integer 0 or 1; other values abort the script.",
        "output_jsonl_path": str(jsonl),
        "jsonl_line_count": len(records),
    }
    if len(records) != history_rows + eval_rows:
        raise SystemExit("JSONL line count does not match history plus eval rows.")
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(summary, indent=2) + "\n"
    SUMMARY_PATH.write_text(text)
    (OUT_DIR / "sample_summary.json").write_text(text)
    print(json.dumps({
        "eval_row_count": eval_rows,
        "eval_fraud_count": eval_fraud,
        "history_row_count": history_rows,
        "step_min_eval": start,
        "step_max_eval": end,
        "jsonl": str(jsonl),
    }))


if __name__ == "__main__":
    main()
