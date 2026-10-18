"""The isolated similar-alert seed. No network and no shared demo database."""

import importlib.util
from pathlib import Path

from app.adapters.level2_pair import (
    EARLIER_ALERT_ID, LATER, LATER_ID, prepare_database, seed_level2_pair,
)
from app.adapters.synthetic import load_transactions
from app.core.rules import analyze
from app.core.store import Store


def columns(store: Store) -> list[str]:
    with store.connect() as db:
        return [row[1] for row in db.execute("PRAGMA table_info(demo_transactions)")]


def test_seed_is_idempotent_and_flags_two_similar_duplicates(tmp_path):
    store = Store(tmp_path / "level2-similar-alerts.db")
    before = columns(store)
    assert seed_level2_pair(store) == 19
    assert seed_level2_pair(store) == 19
    assert columns(store) == before
    rows = {row.id: row for row in store.list_transactions("demo-user-001")}
    assert EARLIER_ALERT_ID in rows and LATER_ID in rows
    assert "txn_syn_001" in rows and "txn_syn_008" in rows
    history = list(rows.values())
    earlier = analyze(rows[EARLIER_ALERT_ID], history, "req_level2")
    later = analyze(rows[LATER_ID], history, "req_level2")
    assert earlier.alert_type == later.alert_type == "duplicate"
    assert earlier.needs_human is True and later.needs_human is True
    assert analyze(rows["txn_syn_003"], history, "req_level2").alert_type == "none"
    assert rows[LATER_ID].merchant_display == rows[EARLIER_ALERT_ID].merchant_display == "StreamWave"
    assert rows[LATER_ID].amount == rows[EARLIER_ALERT_ID].amount == LATER.amount
    assert rows[LATER_ID].merchant_category == "streaming"
    assert rows[LATER_ID].occurred_at == LATER.occurred_at
    untouched = Store(tmp_path / "baseline-only.db")
    assert LATER_ID not in {row.id for row in load_transactions(untouched)}


def test_seed_refuses_the_shared_demo_database(tmp_path):
    demo = tmp_path / "trustledger-demo.db"
    store = Store(demo)
    try:
        seed_level2_pair(store)
    except RuntimeError as exc:
        assert "trustledger-demo.db" in str(exc)
    else:
        raise AssertionError("demo database was seeded")
    assert store.list_transactions("demo-user-001") == []
    cli = _cli()
    assert cli.main(["--database", str(demo)]) == 2
    assert cli.main(["--database", str(tmp_path / "other.db"), "--reset"]) == 2


def _cli():
    path = Path(__file__).resolve().parents[4] / "scripts" / "seed_level2_pair.py"
    spec = importlib.util.spec_from_file_location("seed_level2_pair_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_reset_deletes_only_the_dedicated_file(tmp_path):
    target = tmp_path / "level2-similar-alerts.db"
    neighbor = tmp_path / "trustledger-demo.db"
    neighbor.write_bytes(b"keep")
    assert prepare_database(target) == 19
    assert target.exists()
    assert prepare_database(target, reset=True) == 19
    assert neighbor.read_bytes() == b"keep"
    assert len(Store(target).list_transactions("demo-user-001")) == 19
