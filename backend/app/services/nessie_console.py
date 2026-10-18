import sqlite3
from datetime import datetime, timezone
from time import monotonic

from fastapi import HTTPException

from app.adapters.nessie import REMOTE_ID


def public_body(spec, capture, store, owner, scope):
    if capture["http_status"] != 200 or capture["body_format"] != "json":
        return None
    body = capture["response_body"]
    single = spec.query == "accounts.get"
    rows = [body] if single else body
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return None
    kind = "customer" if spec.query == "customers.list" else "account"
    if spec.query in {"deposits.by_account", "withdrawals.by_account"}:
        kind = None
    if kind:
        if not all(isinstance(row.get("_id"), str) and REMOTE_ID.fullmatch(row["_id"])
                   for row in rows):
            return None
        aliases = store.alias_resources(owner, scope, kind, [row["_id"] for row in rows])
    result = []
    for row in rows:
        projected = {"resource_id": aliases[row["_id"]]} if kind else {}
        enums = ({"type": {"Checking", "Savings", "Credit Card"}} if kind == "account" else
                 {"medium": {"balance"}, "status": {"pending", "completed", "cancelled"}} if not kind else {})
        for key, allowed in enums.items():
            if isinstance(row.get(key), str) and row[key] in allowed:
                projected[key] = row[key]
        for key in (("balance", "rewards") if kind == "account" else ("amount",) if not kind else ()):
            value = row.get(key)
            if type(value) in (int, float) and abs(value) <= 9007199254740991:
                projected[key] = value
        result.append(projected)
    return result[0] if single else result


def execute_query(spec, client, store, owner, scope):
    remote_id = None
    if spec.resource_id:
        remote_id = store.resolve_resource(owner, scope, spec.resource_id)
        if remote_id is None:
            raise HTTPException(404, "resource_not_found")
    started = monotonic()
    requested_at = datetime.now(timezone.utc).isoformat()
    capture = client.query(spec.query, remote_id)
    result = {"source": "nessie", "query": spec.query, "requested_at": requested_at,
              "duration_ms": int((monotonic() - started) * 1000),
              "http_status": capture["http_status"], "transport_error": capture["transport_error"],
              "response_body": None, "body_format": "none"}
    try:
        body = public_body(spec, capture, store, owner, scope)
        result.update(response_body=body, body_format="json" if body is not None else "none")
        history_id = store.append_history(owner, result)
    except (sqlite3.Error, OSError, ValueError):
        return {**result, "history_id": None, "write_status": "failed",
                "write_label": "failed to write"}
    return {**result, "history_id": history_id, "write_status": "saved", "write_label": None}
