from app.adapters.synthetic import load_transactions

import json
import sqlite3
from pathlib import Path

import pytest

from app.core.store import Store


def test_fixture_has_unique_synthetic_transactions():
    rows = load_transactions()
    assert len(rows) == 18
    assert len({row.id for row in rows}) == 18
    assert all(row.source == "synthetic" for row in rows)


def test_sqlite_baseline_matches_offline_contract_fixture():
    expected = json.loads((Path(__file__).resolve().parents[4] /
                           "fixtures/synthetic-transactions.json").read_text())
    assert [row.model_dump(mode="json") for row in load_transactions()] == expected


def test_initialization_is_atomic_owner_scoped_and_does_not_restore_deleted_rows(tmp_path):
    store = Store(tmp_path / "demo.db")
    rows = load_transactions()
    with pytest.raises(sqlite3.IntegrityError):
        store.initialize_transactions("owner", [rows[0], rows[0]])
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM demo_transaction_sets").fetchone()[0] == 0
    load_transactions(store, "owner")
    assert store.list_transactions("other") == []
    with store.connect() as db:
        db.execute("DELETE FROM demo_transactions WHERE owner=?", ("owner",))
    assert load_transactions(Store(store.filename), "owner") == []


def test_runtime_data_sources_do_not_read_json(monkeypatch, tmp_path):
    from app.adapters.nessie_fixture import load_baseline

    opened = Path.open

    def reject_json(path, *args, **kwargs):
        if path.suffix == ".json":
            raise AssertionError("Runtime data sources must use SQLite")
        return opened(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_json)
    store = Store(tmp_path / "sqlite.db")
    assert len(load_transactions(store)) == 18
    assert len(load_baseline(store)["accounts"]) == 18


@pytest.mark.parametrize("change", [{"amount": 0.001}, {"source": "nessie"}])
def test_invalid_demo_write_rolls_back_before_initialization(tmp_path, change):
    store = Store(tmp_path / "invalid.db")
    row = load_transactions()[0].model_copy(update=change)
    with pytest.raises(ValueError):
        store.initialize_transactions("owner", [row])
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM demo_transaction_sets").fetchone()[0] == 0


def test_v1_upgrade_adds_only_missing_transfers_and_preserves_edits_memory_and_empty_sets(tmp_path):
    store = Store(tmp_path / 'legacy.db')
    load_transactions(store)
    load_transactions(store, 'intentionally-empty')
    store.confirm('demo-user-001', 'existing-alert', 'normal', True, 'Sanitized category fact', 'test')
    with store.connect() as db:
        db.execute("DELETE FROM demo_transactions WHERE kind='transfer' OR owner='intentionally-empty'")
        db.execute("UPDATE demo_transactions SET amount_cents=1234 WHERE id='txn_syn_005'")
        db.execute("UPDATE demo_transaction_sets SET version='synthetic-v1'")
        db.execute('ALTER TABLE demo_transactions DROP COLUMN kind')
    restarted = Store(store.filename)
    rows = load_transactions(restarted)
    assert len(rows) == 18 and sum(row.kind == 'transfer' for row in rows) == 10
    assert next(row for row in rows if row.id == 'txn_syn_005').amount == 12.34
    assert load_transactions(Store(store.filename)) == rows
    assert load_transactions(restarted, 'intentionally-empty') == []
    assert restarted.status('demo-user-001', 'existing-alert') == 'normal'
    assert len(restarted.list_memories('demo-user-001')) == 1
