import copy
import json
from pathlib import Path

import pytest

from app.adapters.seed_nessie import BASELINE_SHA256, SeedBlocked, seed_baseline
from app.core.config import Settings
from app.core.store import Store


class Sandbox:
    def __init__(self, store):
        self.store = store
        self.rows = {}
        self.posts = 0
        self.lose_ack = False

    def request(self, method, path, payload=None):
        if method == "POST":
            with self.store.connect() as db:
                assert db.execute("SELECT 1 FROM seed_records WHERE state='pending'").fetchone()
            self.posts += 1
            row = copy.deepcopy(payload)
            row["_id"] = f"{self.posts:024x}"
            if path.startswith("/customers/"):
                row["customer_id"] = path.split("/")[2]
            self.rows.setdefault(path, []).append(row)
            if self.lose_ack:
                return {"http_status": None, "response_body": None}
            return {"http_status": 201, "response_body": "Created"}
        return {"http_status": 200, "response_body": copy.deepcopy(self.rows.get(path, []))}


def test_probe_resumes_with_remote_parents_and_zero_duplicate_creates(tmp_path):
    store = Store(tmp_path / "db")
    settings = Settings(_env_file=None, database_path=store.filename, nessie_api_key="private")
    remote = Sandbox(store)
    result = seed_baseline(settings, store, remote, probe=True)
    assert result["confirmed"] == 8
    assert result["balance_semantics"] == "opening-balance"
    assert remote.posts == 8
    store.confirm(settings.demo_user_id, "example", "normal", True, "Sanitized fact", "test")
    store.delete_history(settings.demo_user_id)
    seed_baseline(settings, store, remote, probe=True)
    assert remote.posts == 8
    assert len(store.list_memories(settings.demo_user_id)) == 1
    assert all("c000000" not in p and "a000000" not in p for p in remote.rows)
    seed_baseline(settings, store, remote)
    assert remote.posts == 124
    seed_baseline(settings, store, remote)
    assert remote.posts == 124


def test_lost_ack_reconciles_and_missing_uncertain_result_blocks(tmp_path):
    store = Store(tmp_path / "db")
    settings = Settings(_env_file=None, database_path=store.filename, nessie_api_key="private")
    remote = Sandbox(store)
    remote.lose_ack = True
    seed_baseline(settings, store, remote, probe=True)
    assert remote.posts == 8
    remote.rows["/customers"] = []
    with pytest.raises(SeedBlocked):
        seed_baseline(settings, store, remote, probe=True)
    assert remote.posts == 8


def test_tampered_baseline_fails_before_remote_writes(tmp_path):
    store = Store(tmp_path / "db")
    settings = Settings(_env_file=None, database_path=store.filename, nessie_api_key="private")
    remote = Sandbox(store)
    baseline = Path(__file__).resolve().parents[4] / "datasets/nessie/baseline.json"
    data = json.loads(baseline.read_text())
    data["customers"][0]["first_name"] = "Changed"
    altered = tmp_path / "baseline.json"
    altered.write_text(json.dumps(data))
    with pytest.raises(SeedBlocked):
        seed_baseline(settings, store, remote, baseline_path=altered)
    assert remote.posts == 0


def test_probe_balance_mismatch_blocks_bulk(tmp_path):
    store = Store(tmp_path / "db")
    settings = Settings(_env_file=None, database_path=store.filename, nessie_api_key="private")
    remote = Sandbox(store)
    seed_baseline(settings, store, remote, probe=True)
    account_path = next(p for p in remote.rows if p.startswith("/customers/"))
    remote.rows[account_path][0]["balance"] += 1
    with pytest.raises(SeedBlocked):
        seed_baseline(settings, store, remote)
    assert remote.posts == 8


def test_unresolved_pending_create_is_never_reposted(tmp_path):
    store = Store(tmp_path / "db")
    settings = Settings(_env_file=None, database_path=store.filename, nessie_api_key="private")

    class LostWrite(Sandbox):
        def request(self, method, path, payload=None):
            if method == "POST":
                self.posts += 1
                return {"http_status": None, "response_body": None}
            return super().request(method, path, payload)

    remote = LostWrite(store)
    for _ in range(2):
        with pytest.raises(SeedBlocked):
            seed_baseline(settings, store, remote, probe=True)
    assert remote.posts == 1


def test_existing_marker_with_different_payload_blocks_before_post(tmp_path):
    store = Store(tmp_path / "db")
    settings = Settings(_env_file=None, database_path=store.filename, nessie_api_key="private")
    remote = Sandbox(store)
    remote.rows["/customers"] = [{"_id": "f" * 24, "first_name": "Changed",
        "last_name": "TL-" + BASELINE_SHA256[:8] + "-c00000000000000000000001"}]
    with pytest.raises(SeedBlocked):
        seed_baseline(settings, store, remote, probe=True)
    assert remote.posts == 0


def test_probe_transaction_drift_and_changed_scope_block_before_bulk_post(tmp_path):
    store = Store(tmp_path / "db")
    settings = Settings(_env_file=None, database_path=store.filename, nessie_api_key="private")
    remote = Sandbox(store)
    seed_baseline(settings, store, remote, probe=True)
    path = next(path for path in remote.rows if path.endswith("/deposits"))
    remote.rows[path][0]["description"] = "Changed"
    with pytest.raises(SeedBlocked):
        seed_baseline(settings, store, remote)
    assert remote.posts == 8
    changed = settings.model_copy(update={"nessie_api_key": Settings(
        _env_file=None, nessie_api_key="changed").nessie_api_key})
    with pytest.raises(SeedBlocked):
        seed_baseline(changed, store, remote, probe=True)
    assert remote.posts == 8


def test_wrong_nonprobe_opening_balance_never_reports_complete(tmp_path):
    store = Store(tmp_path / "db")
    settings = Settings(_env_file=None, database_path=store.filename, nessie_api_key="private")

    class WrongBalance(Sandbox):
        def request(self, method, path, payload=None):
            result = super().request(method, path, payload)
            if method == "POST" and path.endswith("/accounts") and self.posts > 8:
                self.rows[path][-1]["balance"] += 1
            return result

    remote = WrongBalance(store)
    seed_baseline(settings, store, remote, probe=True)
    with pytest.raises(SeedBlocked):
        seed_baseline(settings, store, remote)
    assert remote.posts < 124
