"""Structured SQLite source for the fixed synthetic Nessie import baseline."""
import hashlib
import json

from app.adapters.synthetic_dataset import make_dataset

BASELINE_SHA256 = "546a7e5b20ee37dc94cf615b9a88d49919157eaf01227dfb873ae60f7d8277aa"


def baseline_digest(data):
    return hashlib.sha256((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest()


def load_baseline(store):
    with store.connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS fixture_meta (name TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS fixture_customers (
                id TEXT PRIMARY KEY, first_name TEXT, last_name TEXT,
                street_number TEXT, street_name TEXT, city TEXT, state TEXT, zip TEXT);
            CREATE TABLE IF NOT EXISTS fixture_accounts (
                id TEXT PRIMARY KEY, type TEXT, nickname TEXT, rewards INTEGER,
                balance INTEGER, account_number TEXT,
                customer_id TEXT REFERENCES fixture_customers(id), opening_balance INTEGER);
            CREATE TABLE IF NOT EXISTS fixture_movements (
                kind TEXT CHECK(kind IN ('deposit','withdrawal')), id TEXT,
                account_id TEXT REFERENCES fixture_accounts(id), medium TEXT,
                transaction_date TEXT, status TEXT, amount INTEGER, description TEXT,
                PRIMARY KEY(kind,id));
        """)
        inserted = db.execute("INSERT OR IGNORE INTO fixture_meta VALUES('baseline-v1')").rowcount
        if inserted:
            data = make_dataset("baseline", 10, 18, empty_tail=2)
            if baseline_digest(data) != BASELINE_SHA256:
                raise ValueError("Synthetic baseline identity changed.")
            for row in data["customers"]:
                db.execute("INSERT INTO fixture_customers VALUES(?,?,?,?,?,?,?,?)",
                           (row["_id"], row["first_name"], row["last_name"],
                            *[row["address"][key] for key in
                              ("street_number", "street_name", "city", "state", "zip")]))
            for row in data["accounts"]:
                db.execute("INSERT INTO fixture_accounts VALUES(?,?,?,?,?,?,?,?)",
                           (row["_id"], row["type"], row["nickname"], row["rewards"],
                            row["balance"], row["account_number"], row["customer_id"],
                            data["opening_balances"][row["_id"]]))
                for kind in ("deposit", "withdrawal"):
                    for tx in data[kind + "s_by_account"][row["_id"]]:
                        db.execute("INSERT INTO fixture_movements VALUES(?,?,?,?,?,?,?,?)",
                                   (kind, tx["_id"], row["_id"], tx["medium"],
                                    tx["transaction_date"], tx["status"], tx["amount"],
                                    tx["description"]))
        result = {"synthetic": True, "dataset_id": "baseline", "customers": [], "accounts": [],
                  "deposits_by_account": {}, "withdrawals_by_account": {}, "opening_balances": {}}
        for row in db.execute("SELECT * FROM fixture_customers ORDER BY id"):
            result["customers"].append({"_id": row["id"], "first_name": row["first_name"],
                "last_name": row["last_name"], "address": {key: row[key] for key in
                    ("street_number", "street_name", "city", "state", "zip")}})
        for row in db.execute("SELECT * FROM fixture_accounts ORDER BY id"):
            account_id = row["id"]
            result["accounts"].append({"_id": account_id, **{key: row[key] for key in
                ("type", "nickname", "rewards", "balance", "account_number", "customer_id")}})
            result["opening_balances"][account_id] = row["opening_balance"]
            for kind in ("deposit", "withdrawal"):
                result[kind + "s_by_account"][account_id] = [
                    {"_id": tx["id"], **{key: tx[key] for key in
                        ("medium", "transaction_date", "status", "amount", "description")}}
                    for tx in db.execute("SELECT * FROM fixture_movements WHERE kind=? AND "
                                         "account_id=? ORDER BY id", (kind, account_id))]
        return result
