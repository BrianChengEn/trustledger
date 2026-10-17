"""Explicit local setup only; no runtime route may invoke this importer."""

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.nessie import API_BASE, REMOTE_ID, NessieClient
from app.core.config import Settings
from app.core.store import Store

BASELINE = Path(__file__).resolve().parents[3] / "datasets/nessie/baseline.json"
BASELINE_SHA256 = "546a7e5b20ee37dc94cf615b9a88d49919157eaf01227dfb873ae60f7d8277aa"


class SeedBlocked(RuntimeError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def seed_baseline(settings, store, client=None, *, probe=False, baseline_path=BASELINE):
    raw = baseline_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != BASELINE_SHA256:
        raise SeedBlocked("Baseline checksum changed; reconcile before importing.")
    data = json.loads(raw)
    key = settings.nessie_api_key.get_secret_value()
    if not key:
        raise SeedBlocked("NESSIE_API_KEY is not configured.")
    client = client or NessieClient(key)
    scope = (settings.demo_user_id, digest, API_BASE, hashlib.sha256(key.encode()).hexdigest())
    with store.connect() as db:
        old = db.execute("SELECT * FROM seed_runs WHERE owner=?", (scope[0],)).fetchall()
        if any(tuple(row[k] for k in ("owner", "dataset_sha256", "api_base_url",
                                     "credential_fingerprint")) != scope for row in old):
            raise SeedBlocked("Import scope changed; reconcile existing progress first.")
        db.execute("INSERT OR IGNORE INTO seed_runs(owner,dataset_sha256,api_base_url,"
                   "credential_fingerprint,state,created_at,updated_at) VALUES(?,?,?,?,'active',?,?)",
                   (*scope, now(), now()))
        run = db.execute("SELECT id FROM seed_runs WHERE owner=?", (scope[0],)).fetchone()[0]

    def block(message):
        with store.connect() as db:
            db.execute("UPDATE seed_runs SET state='blocked',updated_at=? WHERE id=?", (now(), run))
        raise SeedBlocked(message)

    def collection(path):
        result = client.request("GET", path)
        rows = result["response_body"]
        if (result["http_status"] != 200 or not isinstance(rows, list)
                or not all(isinstance(row, dict) for row in rows)):
            block("Remote readback failed; no write retry was attempted.")
        return rows

    def create(kind, record, parent_kind=None, parent_local=None):
        parent = None
        if parent_kind:
            with store.connect() as db:
                parent = db.execute("SELECT remote_id FROM seed_records WHERE run_id=? AND kind=?"
                                    " AND local_id=? AND state='confirmed'",
                                    (run, parent_kind, parent_local)).fetchone()
            if not parent:
                block("Parent mapping is not confirmed.")
        marker = "TL-" + digest[:8] + "-" + record["_id"]
        if kind == "customer":
            path = "/customers"
            payload = {k: record[k] for k in ("first_name", "last_name", "address")}
            payload["last_name"] = marker
        elif kind == "account":
            path = f"/customers/{parent['remote_id']}/accounts"
            payload = {k: record[k] for k in ("type", "nickname", "rewards")}
            payload.update(nickname=marker, balance=data["opening_balances"][record["_id"]])
        else:
            path = f"/accounts/{parent['remote_id']}/{kind}s"
            payload = {k: record[k] for k in ("medium", "transaction_date", "status", "amount")}
            payload["description"] = marker
        request_hash = fingerprint(payload)
        marker_field = {"customer": "last_name", "account": "nickname"}.get(kind, "description")
        with store.connect() as db:
            saved = db.execute("SELECT * FROM seed_records WHERE run_id=? AND kind=? AND local_id=?",
                               (run, kind, record["_id"])).fetchone()
        if saved and saved["request_fingerprint"] != request_hash:
            block("Stored request differs; manual reconciliation is required.")

        def matches(row):
            if not isinstance(row, dict) or not REMOTE_ID.fullmatch(str(row.get("_id", ""))):
                return False
            return (all(row.get(k) == value for k, value in payload.items())
                    and (kind != "account" or row.get("customer_id") == parent["remote_id"]))

        if not saved:
            if any(row.get(marker_field) == marker for row in collection(path)):
                block("An untracked synthetic marker exists; reconcile before importing.")
            try:
                with store.connect() as db:
                    db.execute("INSERT INTO seed_records(run_id,kind,local_id,parent_kind,"
                               "parent_local_id,request_fingerprint,state,updated_at)"
                               " VALUES(?,?,?,?,?,?,'pending',?)", (run, kind, record["_id"],
                               parent_kind, parent_local, request_hash, now()))
            except sqlite3.IntegrityError:
                block("Import was claimed by another process; reconcile before retrying.")
            result = client.request("POST", path, payload)
            status = result["http_status"]
            if status is not None and 400 <= status < 500:
                with store.connect() as db:
                    db.execute("UPDATE seed_records SET state='failed',safe_error=? WHERE run_id=?"
                               " AND kind=? AND local_id=?", ("Nessie rejected create", run,
                                                            kind, record["_id"]))
                block("Nessie rejected a create; no automatic retry is allowed.")
        candidates = [row for row in collection(path) if row.get(marker_field) == marker]
        if (len(candidates) != 1 or not matches(candidates[0])
                or (saved and saved["remote_id"] and saved["remote_id"] != candidates[0]["_id"])):
            block("Write outcome is missing or ambiguous; manual reconciliation is required.")
        with store.connect() as db:
            db.execute("UPDATE seed_records SET remote_id=?,state='confirmed',safe_error=NULL,"
                       "updated_at=? WHERE run_id=? AND kind=? AND local_id=?",
                       (candidates[0]["_id"], now(), run, kind, record["_id"]))

    customer = data["customers"][0]
    account = data["accounts"][0]
    probe_keys = {("customer", customer["_id"]), ("account", account["_id"])}
    for kind in ("deposit", "withdrawal"):
        probe_keys.update((kind, row["_id"]) for row in data[kind + "s_by_account"][account["_id"]])
    if not probe:
        with store.connect() as db:
            confirmed = {(r["kind"], r["local_id"]) for r in db.execute(
                "SELECT kind,local_id FROM seed_records WHERE run_id=? AND state='confirmed'", (run,))}
        if not probe_keys <= confirmed:
            block("Run --probe and verify readback before the complete import.")

    def verify_probe():
        create("customer", customer)
        create("account", account, "customer", customer["_id"])
        for kind in ("deposit", "withdrawal"):
            for transaction in data[kind + "s_by_account"][account["_id"]]:
                create(kind, transaction, "account", account["_id"])
        with store.connect() as db:
            remote = db.execute("SELECT remote_id FROM seed_records WHERE run_id=?"
                                " AND kind='account' AND local_id=?",
                                (run, account["_id"])).fetchone()[0]
            parent = db.execute("SELECT remote_id FROM seed_records WHERE run_id=?"
                                " AND kind='customer' AND local_id=?",
                                (run, customer["_id"])).fetchone()[0]
        accounts = collection(f"/customers/{parent}/accounts")
        matched = [row for row in accounts if row.get("_id") == remote]
        if len(matched) != 1 or matched[0].get("balance") != data["opening_balances"][account["_id"]]:
            block("Probe balance differs from its opening balance; stop before further import.")

    if not probe:
        verify_probe()
    for row in (data["customers"][:1] if probe else data["customers"]):
        create("customer", row)
    for row in (data["accounts"][:1] if probe else data["accounts"]):
        create("account", row, "customer", row["customer_id"])
        for kind in ("deposit", "withdrawal"):
            for transaction in data[kind + "s_by_account"][row["_id"]]:
                create(kind, transaction, "account", row["_id"])
    verify_probe()
    with store.connect() as db:
        count = db.execute("SELECT count(*) FROM seed_records WHERE run_id=? AND state='confirmed'",
                           (run,)).fetchone()[0]
        db.execute("UPDATE seed_runs SET state=?,updated_at=? WHERE id=?",
                   ("active" if probe else "complete", now(), run))
    return {"confirmed": count, "probe": probe, "balance_semantics": "opening-balance"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    try:
        result = seed_baseline(settings, Store(settings.database_path), probe=args.probe)
    except SeedBlocked as exc:
        parser.exit(1, f"Import blocked: {exc}\n")
    except (OSError, sqlite3.Error):
        parser.exit(1, "Import blocked; check configuration and reconcile local progress.\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
