"""Opt-in synthetic development library.

The default demo owner and the eight baseline transactions stay untouched.
This module only writes owners whose ids start with dev-library-.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.store import Store
from app.schemas.transaction import Transaction

LIBRARY_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "dev-library" / "transactions.json"
OWNER_PREFIX = "dev-library-"
TRANSACTION_FIELDS = set(Transaction.model_fields)


def load_document(path: Path = LIBRARY_PATH) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("synthetic") is not True:
        raise ValueError("Development library must be marked synthetic.")
    if document.get("ground_truth_fraud_labels") is not False:
        raise ValueError("Development library must not carry fraud ground truth.")
    return document


def transactions_for(owner: str, document: dict | None = None) -> list[Transaction]:
    if not owner.startswith(OWNER_PREFIX):
        raise ValueError("Development library owners must use the dev-library- prefix.")
    document = load_document() if document is None else document
    rows = document["owners"][owner]
    parsed = []
    for row in rows:
        payload = {key: value for key, value in row.items() if key in TRANSACTION_FIELDS}
        parsed.append(Transaction.model_validate(payload))
    if len({row.id for row in parsed}) != len(parsed):
        raise ValueError(f"Duplicate transaction ids for {owner}.")
    return parsed


def seed(store: Store, path: Path = LIBRARY_PATH) -> dict[str, int]:
    """Insert each development owner once. Existing rows, including demo-user-001, stay."""
    document = load_document(path)
    counts: dict[str, int] = {}
    for owner in document["owners"]:
        store.initialize_transactions(owner, transactions_for(owner, document))
        counts[owner] = len(store.list_transactions(owner))
    example = document["confirmation_example"]
    store.confirm(
        example["owner"],
        example["alert_id"],
        example["decision"],
        example["consent_to_memory"],
        "",
        example["request_id"],
        memory_enabled=False,
    )
    return counts


def reset_dev_owners(store: Store) -> list[str]:
    """Delete only dev-library-* owners. demo-user-001 and every other owner stay."""
    with store.connect() as db:
        owners = [
            row[0] for row in db.execute(
                "SELECT owner FROM demo_transaction_sets WHERE owner LIKE ?",
                (OWNER_PREFIX + "%",),
            )
        ]
        for owner in owners:
            if not str(owner).startswith(OWNER_PREFIX):
                raise ValueError("Refusing to reset an owner outside the development library.")
            db.execute("DELETE FROM memory_job_baseline WHERE owner=?", (owner,))
            db.execute("DELETE FROM memory_jobs WHERE owner=?", (owner,))
            db.execute("DELETE FROM confirmations WHERE owner=?", (owner,))
            db.execute("DELETE FROM memories WHERE owner=?", (owner,))
            db.execute("DELETE FROM assistants WHERE owner=?", (owner,))
            db.execute("DELETE FROM demo_transactions WHERE owner=?", (owner,))
            db.execute("DELETE FROM demo_transaction_sets WHERE owner=?", (owner,))
    return owners
