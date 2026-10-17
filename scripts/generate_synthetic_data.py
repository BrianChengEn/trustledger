"""Generate deterministic, local-only Nessie fixtures using the standard library."""

import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re


OUTPUT = Path(__file__).resolve().parents[1] / "datasets" / "nessie"
QUERY_PATHS = {
    "customers.list": "/customers",
    "accounts.list": "/accounts",
    "accounts.get": "/accounts/{id}",
    "accounts.by_customer": "/customers/{id}/accounts",
    "deposits.by_account": "/accounts/{id}/deposits",
    "withdrawals.by_account": "/accounts/{id}/withdrawals",
}


def identifier(prefix, number):
    return f"{prefix}{number:023x}"


def transaction(prefix, number, amount, status="completed"):
    return {
        "_id": identifier(prefix, number),
        "medium": "balance",
        "transaction_date": f"2026-10-{1 + number % 15:02d}",
        "status": status,
        "amount": amount,
        "description": f"Synthetic {prefix} transaction {number}",
    }


def recalculate_balances(dataset):
    for account in dataset["accounts"]:
        account_id = account["_id"]
        deposits = sum(t["amount"] for t in dataset["deposits_by_account"][account_id]
                       if t["status"] == "completed")
        withdrawals = sum(t["amount"] for t in dataset["withdrawals_by_account"][account_id]
                          if t["status"] == "completed")
        account["balance"] = dataset["opening_balances"][account_id] + deposits - withdrawals


def make_dataset(name, customer_count, account_count, empty_tail=0, offset=0):
    customers = [{
        "_id": identifier("c", offset + i),
        "first_name": f"Synthetic{i:03d}",
        "last_name": "TestCustomer",
        "address": {"street_number": str(i), "street_name": "Synthetic Example Road",
                    "city": "Synthetic City", "state": "VA", "zip": "00000"},
    } for i in range(1, customer_count + 1)]
    accounts = [{
        "_id": identifier("a", offset + i),
        "type": ("Checking", "Savings", "Credit Card")[(i - 1) % 3],
        "nickname": f"Synthetic account {i:03d}",
        "rewards": i * 10,
        "balance": 0,
        "account_number": f"9{offset + i:015d}",
        "customer_id": customers[min((i - 1) // 2, customer_count - 1)]["_id"],
    } for i in range(1, account_count + 1)]
    dataset = {
        "synthetic": True, "dataset_id": name,
        "customers": customers, "accounts": accounts,
        "deposits_by_account": {}, "withdrawals_by_account": {}, "opening_balances": {},
    }
    for i, account in enumerate(accounts, 1):
        account_id = account["_id"]
        dataset["opening_balances"][account_id] = 1000 + i * 100
        for collection, prefix, amounts in [
            ("deposits_by_account", "d", (100, 200, 300)),
            ("withdrawals_by_account", "e", (40, 50, 60)),
        ]:
            dataset[collection][account_id] = [
                transaction(prefix, offset * 10 + (i - 1) * 3 + j, amount + i, status)
                for j, (amount, status) in enumerate(zip(amounts, ("completed", "pending", "cancelled")), 1)
            ] if i <= account_count - empty_tail else []
    recalculate_balances(dataset)
    return dataset


def response_for(dataset, query, resource_id=None):
    if query == "customers.list":
        return dataset["customers"]
    if query == "accounts.list":
        return dataset["accounts"]
    if query == "accounts.get":
        return next(a for a in dataset["accounts"] if a["_id"] == resource_id)
    if query == "accounts.by_customer":
        return [a for a in dataset["accounts"] if a["customer_id"] == resource_id]
    collection = {"deposits.by_account": "deposits_by_account",
                  "withdrawals.by_account": "withdrawals_by_account"}[query]
    return dataset[collection][resource_id]


def build_files():
    baseline = make_dataset("baseline", 10, 18, empty_tail=2)
    changed = deepcopy(baseline)
    changed["dataset_id"] = "changed"
    changed["customers"][0]["first_name"] = "Synthetic001Updated"
    changed["customers"][0]["address"]["city"] = "Synthetic Updated City"
    changed["customers"] = [c for c in changed["customers"] if c["_id"] != identifier("c", 9)]
    added = make_dataset("added", 1, 1, offset=1000)
    changed["customers"].extend(added["customers"])
    changed["accounts"] = changed["accounts"][:16] + added["accounts"]
    for collection in ("deposits_by_account", "withdrawals_by_account", "opening_balances"):
        changed[collection] = {k: v for k, v in changed[collection].items()
                               if k not in (identifier("a", 17), identifier("a", 18))}
        changed[collection].update(added[collection])
    changed["accounts"][0].update(nickname="Synthetic renamed account", rewards=35)
    account_id = identifier("a", 1)
    changed["deposits_by_account"][account_id][0]["amount"] += 250
    changed["deposits_by_account"][account_id].pop()
    changed["deposits_by_account"][account_id].append(transaction("d", 1000, 700))
    changed["withdrawals_by_account"][account_id][0].update(amount=61, description="Synthetic corrected withdrawal")
    changed["withdrawals_by_account"][account_id][1]["status"] = "completed"
    changed["withdrawals_by_account"][account_id].append(transaction("e", 1000, 100))
    recalculate_balances(changed)

    boundary = make_dataset("boundary", 3, 4, empty_tail=4, offset=10000)
    boundary["customers"][0].update(first_name="合成資料", last_name="測試 O'Example")
    boundary["customers"][1]["first_name"] = "Synthetic" * 20
    boundary["accounts"][2]["nickname"] = 'Synthetic <script>alert("fixture")</script> & "quotes" 🧪'
    for i, balance in enumerate((0, 2_000_000_000, 100, 1)):
        boundary["opening_balances"][boundary["accounts"][i]["_id"]] = balance
    boundary_id = boundary["accounts"][1]["_id"]
    boundary["deposits_by_account"][boundary_id] = [transaction("d", 100001, 0), transaction("d", 100002, 1)]
    boundary["withdrawals_by_account"][boundary_id] = [transaction("e", 100001, 1)]
    boundary["deposits_by_account"][boundary_id][1]["description"] = 'Synthetic Unicode 測試\n"quoted" <b>text</b> ' * 30
    recalculate_balances(boundary)
    snapshots = {d["dataset_id"]: d for d in (
        baseline, changed, make_dataset("empty", 0, 0), boundary,
        make_dataset("volume", 50, 100, offset=20000),
    )}

    records = []

    def add(dataset_id, query, resource_id=None, *, status=200, body=None, error=None):
        if status == 200 and body is None:
            body = response_for(snapshots[dataset_id], query, resource_id)
        index = len(records) + 1
        record = {
            "id": f"H{index:03d}", "source": "synthetic", "dataset_id": dataset_id,
            "query": query, "resource_id": resource_id, "method": "GET",
            "path": QUERY_PATHS[query].replace("{id}", resource_id or ""),
            "requested_at": (datetime(2026, 10, 17, 10, tzinfo=timezone.utc) + timedelta(minutes=index)).isoformat(),
            "http_status": status, "duration_ms": 25 + index * 7,
            "response_body": deepcopy(body), "transport_error": error,
        }
        records.append(record)
        return record["id"]

    pairs = {}
    examples = []
    for dataset_id in ("baseline", "changed", "boundary"):
        aid = snapshots[dataset_id]["accounts"][0]["_id"]
        cid = snapshots[dataset_id]["customers"][0]["_id"]
        for query in QUERY_PATHS:
            resource_id = None if query.endswith(".list") else cid if query == "accounts.by_customer" else aid
            record_id = add(dataset_id, query, resource_id)
            pairs[dataset_id, query] = record_id
            if dataset_id == "baseline":
                examples.append({"query": query, "history_record_id": record_id})
    for query in ("customers.list", "accounts.list"):
        add("empty", query)
    add("baseline", "accounts.by_customer", identifier("c", 10))
    for query in ("deposits.by_account", "withdrawals.by_account"):
        add("baseline", query, identifier("a", 17))
    reordered = add("baseline", "accounts.list", body=list(reversed(baseline["accounts"])))
    repeated = add("baseline", "accounts.get", account_id)
    removed_before = add("baseline", "accounts.get", identifier("a", 17))
    removed_after = add("changed", "accounts.get", identifier("a", 17), status=404,
                        body={"code": 404, "message": "Synthetic account not found"})
    add("baseline", "accounts.list", status=401, body="unauthorized")
    add("baseline", "accounts.get", "not-an-id", status=400,
        body={"code": 400, "message": "Synthetic invalid account ID"})
    add("baseline", "accounts.get", "f" * 24, status=404,
        body={"code": 404, "message": "Synthetic account not found"})
    add("baseline", "customers.list", status=500,
        body={"code": 500, "message": "Synthetic upstream error", "details": "Credentials: [REDACTED]"})
    add("baseline", "accounts.list", status=None,
        error={"type": "timeout", "message": "Synthetic transport timeout; no HTTP response"})
    comparisons = [
        {"id": "CMP001", "left_id": pairs["baseline", "accounts.get"], "right_id": pairs["changed", "accounts.get"],
         "expected": {"kind": "object_changed", "changed_fields": ["balance", "nickname", "rewards"]}},
        {"id": "CMP002", "left_id": pairs["baseline", "deposits.by_account"], "right_id": pairs["changed", "deposits.by_account"],
         "expected": {"kind": "collection_changed", "added_ids": [identifier("d", 1000)], "removed_ids": [identifier("d", 3)],
                      "updated_fields": {identifier("d", 1): ["amount"]}}},
        {"id": "CMP003", "left_id": pairs["baseline", "customers.list"], "right_id": pairs["changed", "customers.list"],
         "expected": {"kind": "collection_changed", "added_ids": [identifier("c", 1001)], "removed_ids": [identifier("c", 9)],
                      "updated_fields": {identifier("c", 1): ["first_name", "address.city"]}}},
        {"id": "CMP004", "left_id": pairs["baseline", "accounts.list"], "right_id": reordered,
         "expected": {"kind": "same_records_different_order"}},
        {"id": "CMP005", "left_id": pairs["baseline", "accounts.get"], "right_id": repeated,
         "expected": {"kind": "identical_body"}},
        {"id": "CMP006", "left_id": removed_before, "right_id": removed_after,
         "expected": {"kind": "account_removed", "http_statuses": [200, 404]}},
        {"id": "CMP007", "left_id": pairs["baseline", "withdrawals.by_account"], "right_id": pairs["changed", "withdrawals.by_account"],
         "expected": {"kind": "collection_changed", "added_ids": [identifier("e", 1000)], "removed_ids": [],
                      "updated_fields": {identifier("e", 1): ["amount", "description"], identifier("e", 2): ["status"]}}},
    ]
    manifest = {
        "synthetic": True, "schema_reference": "https://prod.nessieisreal.com/nessie-openapi-spec.yaml",
        "schema_version": "1.0.0", "network_requests_made": False,
        "withdrawal_fields_reference": "https://prod.nessieisreal.com/docs",
        "query_examples": examples,
        "datasets": {name: {"file": f"{name}.json", "counts": {
            "customers": len(d["customers"]), "accounts": len(d["accounts"]),
            "deposits": sum(map(len, d["deposits_by_account"].values())),
            "withdrawals": sum(map(len, d["withdrawals_by_account"].values())),
        }} for name, d in snapshots.items()},
        "history_records": len(records), "comparison_cases": len(comparisons),
    }
    return {**{f"{name}.json": d for name, d in snapshots.items()},
            "history.json": {"synthetic": True, "records": records, "comparisons": comparisons},
            "manifest.json": manifest}


def validate_dataset(dataset):
    assert dataset["synthetic"] is True
    customers = {c["_id"] for c in dataset["customers"]}
    accounts = {a["_id"] for a in dataset["accounts"]}
    assert len(customers) == len(dataset["customers"])
    assert len(accounts) == len(dataset["accounts"])
    ids = set()
    for record in dataset["customers"] + dataset["accounts"]:
        assert re.fullmatch(r"[0-9a-f]{24}", record["_id"])
        assert record["_id"] not in ids
        ids.add(record["_id"])
    for customer in dataset["customers"]:
        assert set(customer) == {"_id", "first_name", "last_name", "address"}
        assert all(isinstance(customer[k], str) for k in ("first_name", "last_name"))
        assert set(customer["address"]) == {"street_number", "street_name", "city", "state", "zip"}
        assert all(isinstance(v, str) for v in customer["address"].values())
    numbers = set()
    for account in dataset["accounts"]:
        assert set(account) == {"_id", "type", "nickname", "rewards", "balance", "account_number", "customer_id"}
        assert account["customer_id"] in customers
        assert account["type"] in {"Checking", "Savings", "Credit Card"}
        assert isinstance(account["nickname"], str)
        assert all(type(account[k]) is int and 0 <= account[k] <= 2**53 - 1 for k in ("rewards", "balance"))
        assert re.fullmatch(r"9[0-9]{15}", account["account_number"])
        assert account["account_number"] not in numbers
        numbers.add(account["account_number"])
    assert set(dataset["opening_balances"]) == accounts
    for collection in ("deposits_by_account", "withdrawals_by_account"):
        assert set(dataset[collection]) == accounts
        for transactions in dataset[collection].values():
            for item in transactions:
                assert set(item) == {"_id", "medium", "transaction_date", "status", "amount", "description"}
                assert re.fullmatch(r"[0-9a-f]{24}", item["_id"]) and item["_id"] not in ids
                ids.add(item["_id"])
                assert type(item["amount"]) is int and 0 <= item["amount"] <= 2**53 - 1
                assert all(isinstance(item[k], str) for k in ("medium", "transaction_date", "status", "description"))
                date.fromisoformat(item["transaction_date"])
    calculated = deepcopy(dataset)
    recalculate_balances(calculated)
    assert calculated["accounts"] == dataset["accounts"]


def validate_files(files):
    manifest = files["manifest.json"]
    for name, entry in manifest["datasets"].items():
        dataset = files[entry["file"]]
        validate_dataset(dataset)
        assert dataset["dataset_id"] == name
        assert entry["counts"] == {
            "customers": len(dataset["customers"]), "accounts": len(dataset["accounts"]),
            "deposits": sum(map(len, dataset["deposits_by_account"].values())),
            "withdrawals": sum(map(len, dataset["withdrawals_by_account"].values())),
        }
    history = files["history.json"]
    records = {r["id"]: r for r in history["records"]}
    assert len(records) == len(history["records"]) == manifest["history_records"]
    assert len(history["comparisons"]) == manifest["comparison_cases"]
    for record in records.values():
        assert record["source"] == "synthetic" and record["method"] == "GET"
        assert record["path"] == QUERY_PATHS[record["query"]].replace("{id}", record["resource_id"] or "")
        assert "?" not in record["path"] and record["duration_ms"] >= 0
        datetime.fromisoformat(record["requested_at"])
        if record["http_status"] is None:
            assert record["response_body"] is None and record["transport_error"]
        else:
            assert record["transport_error"] is None
        if record["http_status"] == 200:
            expected = response_for(files[f'{record["dataset_id"]}.json'], record["query"], record["resource_id"])
            body = record["response_body"]
            if isinstance(body, list):
                assert {r["_id"]: r for r in body} == {r["_id"]: r for r in expected}
            else:
                assert body == expected
    assert {records[e["history_record_id"]]["query"] for e in manifest["query_examples"]} == set(QUERY_PATHS)
    for case in history["comparisons"]:
        left, right = records[case["left_id"]], records[case["right_id"]]
        assert (left["query"], left["resource_id"]) == (right["query"], right["resource_id"])
        expected = case["expected"]
        a, b = left["response_body"], right["response_body"]
        if expected["kind"] == "collection_changed":
            a, b = {r["_id"]: r for r in a}, {r["_id"]: r for r in b}
            assert sorted(b.keys() - a.keys()) == sorted(expected["added_ids"])
            assert sorted(a.keys() - b.keys()) == sorted(expected["removed_ids"])
            assert {key for key in a.keys() & b.keys() if a[key] != b[key]} == set(expected["updated_fields"])
            for key, fields in expected["updated_fields"].items():
                for field in fields:
                    old, new = a[key], b[key]
                    for part in field.split("."):
                        old, new = old[part], new[part]
                    assert old != new
        elif expected["kind"] == "object_changed":
            assert sorted(k for k in a if a[k] != b[k]) == sorted(expected["changed_fields"])
        elif expected["kind"] == "same_records_different_order":
            assert a != b and {r["_id"]: r for r in a} == {r["_id"]: r for r in b}
        elif expected["kind"] == "identical_body":
            assert a == b
        elif expected["kind"] == "account_removed":
            assert [left["http_status"], right["http_status"]] == expected["http_statuses"]
        else:
            raise AssertionError(f"Unknown comparison case: {expected['kind']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate existing files without writing")
    args = parser.parse_args()
    expected = build_files()
    if args.check:
        actual = {name: json.loads((OUTPUT / name).read_text(encoding="utf-8")) for name in expected}
        validate_files(actual)
        assert actual == expected, "Generated files differ from the deterministic fixtures"
        print(f"Verified {len(actual)} JSON files, six queries, and seven comparison cases.")
    else:
        validate_files(expected)
        OUTPUT.mkdir(parents=True, exist_ok=True)
        for name, payload in expected.items():
            (OUTPUT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Generated {len(expected)} JSON files in {OUTPUT}")


if __name__ == "__main__":
    main()
