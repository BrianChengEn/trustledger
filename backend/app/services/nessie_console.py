import sqlite3
from datetime import datetime, timezone
from time import monotonic

from fastapi import HTTPException

def execute_query(spec, client, store, owner):
    started = monotonic()
    requested_at = datetime.now(timezone.utc).isoformat()
    capture = client.query(spec.query, spec.resource_id)
    result = {"source": "nessie", "query": spec.query, "resource_id": spec.resource_id,
              "requested_at": requested_at, "duration_ms": int((monotonic() - started) * 1000),
              **capture}
    try:
        history_id = store.append_history(owner, result)
    except (sqlite3.Error, OSError, ValueError):
        return {**result, "history_id": None, "write_status": "failed",
                "write_label": "failed to write"}
    return {**result, "history_id": history_id, "write_status": "saved", "write_label": None}


def compare_snapshots(left, right):
    if any(left[k] != right[k] for k in ("query", "resource_id", "source")):
        raise HTTPException(409, "incompatible_history")
    changes = []
    missing = object()

    def walk(before, after, path="", record_id=None):
        if before is missing or after is missing:
            kind = "added" if before is missing else "removed"
        elif isinstance(before, dict) and isinstance(after, dict):
            for key in sorted(before.keys() | after.keys()):
                pointer = str(key).replace("~", "~0").replace("/", "~1")
                walk(before.get(key, missing), after.get(key, missing), path + "/" + pointer,
                     record_id)
            return
        elif isinstance(before, list) and isinstance(after, list):
            for i in range(max(len(before), len(after))):
                walk(before[i] if i < len(before) else missing,
                     after[i] if i < len(after) else missing, path + f"/{i}", record_id)
            return
        elif type(before) is type(after) and before == after:
            return
        else:
            kind = "changed"
        change = {"kind": kind, "path": path, "before_present": before is not missing,
                  "after_present": after is not missing,
                  "before": None if before is missing else before,
                  "after": None if after is missing else after}
        if record_id is not None:
            change["record_id"] = record_id
        changes.append(change)

    before, after = left["response_body"], right["response_body"]
    if (isinstance(before, list) and isinstance(after, list)
            and all(r["http_status"] is not None and 200 <= r["http_status"] < 300
                    for r in (left, right))):
        def by_id(rows):
            result = {}
            for row in rows:
                if (not isinstance(row, dict) or not isinstance(row.get("_id"), str)
                        or not row["_id"] or row["_id"] in result):
                    raise HTTPException(409, "unmatchable_collection")
                result[row["_id"]] = row
            return result
        old, new = by_id(before), by_id(after)
        for record_id in sorted(old.keys() | new.keys()):
            walk(old.get(record_id, missing), new.get(record_id, missing), record_id=record_id)
    else:
        walk(before, after)
    status_change = (None if left["http_status"] == right["http_status"] else
                     {"before": left["http_status"], "after": right["http_status"]})
    transport_change = (None if left["transport_error"] == right["transport_error"] else
                        {"before": left["transport_error"], "after": right["transport_error"]})
    return {"data_changed": bool(changes or status_change or transport_change), "changes": changes,
            "status_change": status_change, "transport_change": transport_change}


def compare_history(store, owner, left_id, right_id):
    left, right = store.get_history(owner, left_id), store.get_history(owner, right_id)
    if left is None or right is None:
        raise HTTPException(404, "history_not_found")
    return {"left": left, "right": right, "comparison": compare_snapshots(left, right)}
