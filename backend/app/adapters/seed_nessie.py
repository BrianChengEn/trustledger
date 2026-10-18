"""Explicit local setup only; no runtime route may invoke this importer."""

import argparse
import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

from app.adapters.nessie import API_BASE, REMOTE_ID, NessieClient
from app.adapters.nessie_fixture import BASELINE_SHA256, baseline_digest, load_baseline
from app.core.config import Settings
from app.core.store import Store

class SeedBlocked(RuntimeError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def seed_baseline(settings, store, client=None, *, probe=False, baseline_path=None):
    if baseline_path is not None:
        raise SeedBlocked("JSON import sources are disabled; use the SQLite baseline.")
    data = load_baseline(store)
    digest = baseline_digest(data)
    if digest != BASELINE_SHA256:
        raise SeedBlocked("Baseline checksum changed; reconcile before importing.")
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


def seed_transfers(settings, store, client=None):
    """Explicitly top up confirmed sandbox accounts; never invoked by runtime routes."""
    from app.services.workspace import collection, movements, token

    key = settings.nessie_api_key.get_secret_value()
    if settings.transaction_provider != 'nessie' or not key:
        raise SeedBlocked('Select Nessie and configure its backend key before transfer setup.')
    if baseline_digest(load_baseline(store)) != BASELINE_SHA256:
        raise SeedBlocked('Baseline checksum changed; reconcile before transfer setup.')
    owner, scope = settings.demo_user_id, hashlib.sha256(key.encode()).hexdigest()
    with store.connect() as db:
        confirmed = db.execute("SELECT a.remote_id,c.remote_id AS customer FROM seed_records a "
                               "JOIN seed_records c ON c.run_id=a.run_id AND c.kind='customer' "
                               "AND c.local_id=a.parent_local_id JOIN seed_runs s ON s.id=a.run_id "
                               "WHERE s.owner=? AND s.dataset_sha256=? AND s.api_base_url=? "
                               "AND s.credential_fingerprint=? AND a.kind='account' "
                               "AND a.state='confirmed' AND c.state='confirmed'",
                               (owner, BASELINE_SHA256, API_BASE, scope)).fetchall()
        db.execute("CREATE TABLE IF NOT EXISTS nessie_setup_operations ("
                   "owner TEXT NOT NULL,credential_scope TEXT NOT NULL,operation TEXT NOT NULL,"
                   "request_fingerprint TEXT NOT NULL,state TEXT NOT NULL "
                   "CHECK(state IN ('pending','confirmed','failed')),http_status INTEGER,updated_at TEXT NOT NULL,"
                   "PRIMARY KEY(owner,credential_scope,operation))")
    parents = {row['remote_id']: row['customer'] for row in confirmed}
    if not parents:
        raise SeedBlocked('Confirmed baseline account mappings are required.')
    client = client or NessieClient(key)

    def read(path, *, allow_missing=False):
        capture = client.request('GET', path)
        if allow_missing and capture['http_status'] == 404:
            return None
        if capture['http_status'] != 200:
            raise SeedBlocked('Transfer setup read failed; no automatic write retry was attempted.')
        try:
            return collection(capture)
        except (TypeError, ValueError):
            raise SeedBlocked('Transfer setup received an invalid collection.') from None

    accounts = read('/accounts')
    if any(row['_id'] not in parents or row.get('customer_id') != parents[row['_id']]
           for row in accounts):
        raise SeedBlocked('An account lacks its confirmed baseline customer mapping.')
    created = total = 0
    for account in accounts:
        remote = account['_id']
        customer = account['customer_id']
        code = store.alias_resources(owner, scope, 'customer', [customer])[customer]
        customer_owner = f'{owner}:nessie:{scope}:{code}'
        account_code = token('acct_', customer_owner, remote)
        path = f'/accounts/{remote}/transfers'

        def transfers(*, allow_missing=False):
            rows = read(path, allow_missing=allow_missing)
            if rows is not None:
                try:
                    movements(rows, customer_owner, remote, 'transfers')
                except (TypeError, ValueError):
                    raise SeedBlocked('Transfer readback failed validation.') from None
            return rows

        rows = transfers(allow_missing=True) or []
        for number in range(1, 11):
            operation = f'v021-transfer-usd:{account_code}:{number}'
            marker = 'TL-' + operation
            # Nessie truncates fractional transfer amounts; whole-dollar fixtures round-trip exactly.
            payload = {'amount': 10 + number * 7,
                       'transaction_date': (date(2026, 10, 18) - timedelta(days=number)).isoformat(),
                       'status': 'pending' if number % 5 == 0 else 'completed', 'description': marker}
            request_hash = fingerprint(payload)
            identity = (owner, scope, operation)
            with store.connect() as db:
                saved = db.execute('SELECT * FROM nessie_setup_operations WHERE owner=? '
                                   'AND credential_scope=? AND operation=?', identity).fetchone()
            candidates = [row for row in rows if row.get('description') == marker]
            if saved:
                if saved['request_fingerprint'] != request_hash or saved['state'] == 'failed':
                    raise SeedBlocked('Transfer setup requires manual reconciliation.')
            else:
                if len(rows) >= 10:
                    break
                if candidates:
                    raise SeedBlocked('An untracked transfer marker requires reconciliation.')
                try:
                    with store.connect() as db:
                        db.execute("INSERT INTO nessie_setup_operations VALUES(?,?,?,?,'pending',NULL,?)",
                                   (*identity, request_hash, now()))
                except sqlite3.IntegrityError:
                    raise SeedBlocked('Transfer setup was claimed by another process.') from None
                capture = client.request('POST', path, payload)
                status = capture['http_status']
                with store.connect() as db:
                    db.execute('UPDATE nessie_setup_operations SET http_status=?,updated_at=?,state=? '
                               'WHERE owner=? AND credential_scope=? AND operation=?',
                               (status, now(), 'failed' if status is not None and 400 <= status < 500
                                else 'pending', *identity))
                if status is not None and 400 <= status < 500:
                    raise SeedBlocked('Nessie rejected transfer creation; no automatic retry is allowed.')
                rows = transfers()
                candidates = [row for row in rows if row.get('description') == marker]
                created += 1
            if (len(candidates) != 1
                    or any(candidates[0].get(name) != value for name, value in payload.items())):
                raise SeedBlocked('Transfer outcome is missing or ambiguous; reconcile without reposting.')
            with store.connect() as db:
                db.execute("UPDATE nessie_setup_operations SET state='confirmed',updated_at=? "
                           'WHERE owner=? AND credential_scope=? AND operation=?', (now(), *identity))
        if len(rows) < 10:
            raise SeedBlocked('Transfer coverage is incomplete; reconcile existing setup operations.')
        total += len(rows)
    return {'accounts': len(accounts), 'transfers': total, 'created': created}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--probe", action="store_true")
    operation.add_argument("--transfers", action="store_true", help='Top up existing confirmed accounts to 10 transfers.')
    args = parser.parse_args()
    settings = Settings()
    try:
        store = Store(settings.database_path)
        result = (seed_transfers(settings, store) if args.transfers else
                  seed_baseline(settings, store, probe=args.probe))
    except SeedBlocked as exc:
        parser.exit(1, f"Import blocked: {exc}\n")
    except (OSError, sqlite3.Error):
        parser.exit(1, "Import blocked; check configuration and reconcile local progress.\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
