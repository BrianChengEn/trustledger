"""Demo sign-in, role enforcement and admin editing of the synthetic demo data (no external services)."""
import base64
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.adapters.synthetic import load_transactions
from app.core import auth
from app.core.config import Settings
from app.core.store import Store
from app.main import create_app

ORIGIN = "http://localhost:5173"
USER_PASS, ADMIN_PASS, SECRET = "user-pass", "admin-pass", "s" * 40


def make_client(tmp_path, **overrides):
    values = dict(_env_file=None, database_path=tmp_path / "t.db", require_login=True,
                  demo_user_passcode=USER_PASS, demo_admin_passcode=ADMIN_PASS, session_secret=SECRET,
                  allow_demo_edit=True, allow_memory_write=True, backboard_api_key="", jev_api_key="", nessie_api_key="")
    values.update(overrides)
    client = TestClient(create_app(Settings(**values)), base_url="http://127.0.0.1")
    client.headers.update({"origin": ORIGIN, "content-type": "application/json"})
    return client


@pytest.fixture(autouse=True)
def fresh_throttle():
    auth.reset_failures()
    yield
    auth.reset_failures()


@pytest.fixture
def anon(tmp_path):
    with make_client(tmp_path) as client:
        yield client


def sign_in(client, role, passcode):
    return client.post("/api/v1/auth/login", json={"role": role, "passcode": passcode})


@pytest.fixture
def admin(anon):
    assert sign_in(anon, "admin", ADMIN_PASS).status_code == 200
    return anon


@pytest.fixture
def user(tmp_path):
    with make_client(tmp_path) as client:
        assert sign_in(client, "user", USER_PASS).status_code == 200
        yield client


def code(response, status):
    assert response.status_code == status, response.text
    return response.json()["error"]["code"]


# ---------------------------------------------------------------- sign-in ----
def test_session_view_before_sign_in(anon):
    body = anon.get("/api/v1/auth/me").json()
    assert body == {"authenticated": False, "role": None, "login_required": True, "admin_available": True,
                    "demo_edit_enabled": True}


def test_data_routes_need_a_session_but_health_does_not(anon):
    assert anon.get("/api/v1/health").status_code == 200
    for path in ("/api/v1/transactions", "/api/v1/alerts", "/api/v1/memories", "/api/v1/privacy/preview/txn_syn_004"):
        assert code(anon.get(path), 401) == "auth_required"
    assert code(anon.post("/api/v1/workspace/refresh", json={}), 401) == "auth_required"


def test_wrong_passcode_is_rejected_and_sets_no_cookie(anon):
    response = sign_in(anon, "user", "nope")
    assert code(response, 401) == "invalid_credentials"
    assert "tl_session" not in response.headers.get("set-cookie", "")
    assert anon.get("/api/v1/transactions").status_code == 401


def test_user_session_reads_data_but_cannot_use_admin_routes(user):
    assert user.get("/api/v1/auth/me").json()["role"] == "user"
    assert user.get("/api/v1/transactions").status_code == 200
    assert code(user.get("/api/v1/admin/demo/transactions"), 403) == "admin_only"
    assert code(user.post("/api/v1/admin/demo/reset"), 403) == "admin_only"
    assert code(user.get("/api/v1/admin/nessie/history"), 403) == "admin_only"


def test_admin_session_reaches_demo_and_user_routes(admin):
    assert admin.get("/api/v1/auth/me").json()["role"] == "admin"
    assert admin.get("/api/v1/transactions").status_code == 200
    assert admin.get("/api/v1/admin/demo/transactions").status_code == 200
    # Past the auth gate the console reports its own state: no Nessie key is configured in this test.
    assert code(admin.get("/api/v1/admin/nessie/history"), 503) == "nessie_not_configured"


def test_session_cookie_is_httponly_samesite_strict(anon):
    flags = sign_in(anon, "user", USER_PASS).headers["set-cookie"].lower()
    assert "httponly" in flags and "samesite=strict" in flags and "path=/" in flags


def test_logout_ends_the_session(user):
    assert user.post("/api/v1/auth/logout").json()["authenticated"] is False
    user.cookies.clear()
    assert user.get("/api/v1/transactions").status_code == 401


def test_admin_sign_in_is_off_without_a_passcode(tmp_path):
    with make_client(tmp_path, demo_admin_passcode="") as client:
        assert client.get("/api/v1/auth/me").json()["admin_available"] is False
        assert code(sign_in(client, "admin", ""), 403) == "admin_not_configured"
        assert code(sign_in(client, "admin", "anything"), 403) == "admin_not_configured"
        assert client.get("/api/v1/admin/demo/transactions").status_code == 401


def test_user_sign_in_is_open_when_no_user_passcode(tmp_path):
    with make_client(tmp_path, demo_user_passcode="") as client:
        assert sign_in(client, "user", "").status_code == 200
        assert client.get("/api/v1/transactions").status_code == 200


def test_tampered_or_expired_cookies_are_rejected(anon):
    token = sign_in(anon, "user", USER_PASS).cookies["tl_session"]
    body, signature = token.split(".")
    forged = base64.urlsafe_b64encode(json.dumps({"role": "admin", "exp": int(time.time()) + 999}).encode()).decode().rstrip("=")
    for bad in (forged + "." + signature, body + "." + "A" * len(signature), "garbage", body, ""):
        anon.cookies.clear()
        anon.cookies.set("tl_session", bad)
        assert anon.get("/api/v1/transactions").status_code == 401, bad
    # A correctly signed but expired session
    secret = SECRET.encode()
    expired = base64.urlsafe_b64encode(json.dumps({"role": "admin", "exp": int(time.time()) - 5},
                                                  separators=(",", ":")).encode())
    anon.cookies.clear()
    anon.cookies.set("tl_session", expired.decode().rstrip("=") + "." + auth._sign(secret, expired))
    assert anon.get("/api/v1/admin/demo/transactions").status_code == 401


def test_repeated_wrong_passcodes_are_throttled(anon):
    for _ in range(auth.MAX_FAILURES):
        assert sign_in(anon, "user", "wrong").status_code == 401
    assert code(sign_in(anon, "user", "wrong"), 429) == "too_many_attempts"
    assert sign_in(anon, "user", USER_PASS).status_code == 429  # locked out even with the right passcode for a minute


def test_passcodes_never_appear_in_responses(anon):
    for response in (sign_in(anon, "admin", "wrong"), sign_in(anon, "admin", ADMIN_PASS), anon.get("/api/v1/auth/me")):
        assert ADMIN_PASS not in response.text and USER_PASS not in response.text and SECRET not in response.text


def test_login_enforcement_is_off_by_default(tmp_path):
    with make_client(tmp_path, require_login=False) as client:
        assert client.get("/api/v1/transactions").status_code == 200
        assert client.get("/api/v1/auth/me").json()["login_required"] is False
        # Demo editing still needs an admin session even when sign-in is not enforced.
        assert code(client.get("/api/v1/admin/demo/transactions"), 401) == "auth_required"


# ------------------------------------------------------------- demo editing ----
GOOD = {"merchant": "Test Cafe", "category": "dining", "amount": 12.5, "occurred_at": "2026-10-18T09:30:00-04:00"}


def test_demo_editing_is_off_unless_enabled(tmp_path):
    with make_client(tmp_path, allow_demo_edit=False) as client:
        sign_in(client, "admin", ADMIN_PASS)
        assert client.get("/api/v1/admin/demo/status").json() == {"enabled": False, "rows": 0, "cap": 60}
        assert code(client.get("/api/v1/admin/demo/transactions"), 403) == "demo_edit_disabled"
        assert code(client.post("/api/v1/admin/demo/transactions", json=GOOD), 403) == "demo_edit_disabled"
        assert code(client.post("/api/v1/admin/demo/reset"), 403) == "demo_edit_disabled"


def test_list_shows_the_baseline(admin):
    assert admin.get("/api/v1/admin/demo/status").json() == {"enabled": True, "rows": 18, "cap": 60}
    rows = admin.get("/api/v1/admin/demo/transactions").json()
    assert len(rows) == 18 and {r["origin"] for r in rows} == {"baseline"} and not any(r["decided"] for r in rows)
    assert all(r["edited_at"] is None for r in rows)


def test_created_charge_is_synthetic_and_visible_to_the_user_view(admin):
    created = admin.post("/api/v1/admin/demo/transactions", json=GOOD)
    assert created.status_code == 201
    row = created.json()
    assert row["origin"] == "admin" and row["id"].startswith("txn_syn_adm_") and row["amount"] == 12.5
    seen = {t["id"]: t for t in admin.get("/api/v1/transactions?limit=100").json()}
    assert seen[row["id"]]["source"] == "synthetic" and seen[row["id"]]["account_token"] == "acct_demo_a1"
    assert seen[row["id"]]["merchant_display"] == "Test Cafe"


def test_a_big_purchase_raises_a_real_alert(admin):
    row = admin.post("/api/v1/admin/demo/transactions", json={**GOOD, "merchant": "Big Gadgets", "category": "electronics",
                                                                "amount": 999.0}).json()
    alert = next(a for a in admin.get("/api/v1/alerts").json() if a["transaction_id"] == row["id"])
    assert alert["alert_type"] == "amount_anomaly" and alert["status"] == "open"


@pytest.mark.parametrize("change", [
    {"amount": 0}, {"amount": -5}, {"amount": 12.345}, {"amount": 100000}, {"amount": "abc"},
    {"merchant": ""}, {"merchant": "   "}, {"merchant": "x" * 81}, {"merchant": "bad\x00name"}, {"merchant": "line\nbreak"},
    {"category": "crypto"}, {"category": ""}, {"occurred_at": "2026-10-18T09:30:00"}, {"occurred_at": "yesterday"},
    {"direction": "unknown"}, {"source": "nessie"}, {"id": "txn_evil"}, {"account_token": "acct_other"}, {"kind": "transfer"},
])
def test_invalid_input_is_rejected_without_changing_anything(admin, change):
    response = admin.post("/api/v1/admin/demo/transactions", json={**GOOD, **change})
    assert code(response, 422) == "invalid_request"
    assert admin.get("/api/v1/admin/demo/status").json()["rows"] == 18
    assert "invalid" not in response.text.lower().replace("invalid_request", "")  # no raw input echoed back


def test_row_cap(admin):
    for _ in range(42):
        assert admin.post("/api/v1/admin/demo/transactions", json=GOOD).status_code == 201
    assert code(admin.post("/api/v1/admin/demo/transactions", json=GOOD), 409) == "row_cap"
    assert code(admin.post("/api/v1/admin/demo/scenarios/duplicate"), 409) == "row_cap"
    assert admin.get("/api/v1/admin/demo/status").json()["rows"] == 60


def test_update_and_delete(admin):
    tx = admin.post("/api/v1/admin/demo/transactions", json=GOOD).json()["id"]
    changed = admin.patch(f"/api/v1/admin/demo/transactions/{tx}", json={"amount": 99.99, "merchant": "Renamed"}).json()
    assert changed["amount"] == 99.99 and changed["merchant_display"] == "Renamed" and changed["edited_at"]
    assert admin.patch(f"/api/v1/admin/demo/transactions/{tx}", json={}).status_code == 422
    assert admin.patch(f"/api/v1/admin/demo/transactions/{tx}", json={"amount": -1}).status_code == 422
    assert code(admin.patch("/api/v1/admin/demo/transactions/txn_nope", json={"amount": 5}), 404) == "not_found"
    assert admin.delete(f"/api/v1/admin/demo/transactions/{tx}").status_code == 204
    assert code(admin.delete(f"/api/v1/admin/demo/transactions/{tx}"), 404) == "not_found"
    assert admin.get("/api/v1/admin/demo/status").json()["rows"] == 18


def test_a_decided_charge_cannot_be_edited_or_deleted(admin):
    alert = admin.get("/api/v1/alerts").json()[0]
    tx = alert["transaction_id"]
    assert admin.post(f"/api/v1/alerts/{alert['alert_id']}/confirmations",
                      json={"decision": "review", "consent_to_memory": False}).status_code == 200
    row = next(r for r in admin.get("/api/v1/admin/demo/transactions").json() if r["id"] == tx)
    assert row["decided"] is True
    assert code(admin.patch(f"/api/v1/admin/demo/transactions/{tx}", json={"amount": 1}), 409) == "decision_exists"
    assert code(admin.delete(f"/api/v1/admin/demo/transactions/{tx}"), 409) == "decision_exists"


@pytest.mark.parametrize("scenario,alert_type", [("duplicate", "duplicate"), ("large_purchase", "amount_anomaly"),
                                                 ("price_hike", "subscription_change")])
def test_scenarios_create_the_alert_they_promise(admin, scenario, alert_type):
    before = {a["alert_id"] for a in admin.get("/api/v1/alerts").json()}
    created = admin.post(f"/api/v1/admin/demo/scenarios/{scenario}").json()
    assert created["scenario"] == scenario and created["created"]
    new = [a for a in admin.get("/api/v1/alerts").json() if a["alert_id"] not in before]
    assert [a["alert_type"] for a in new] == [alert_type]
    assert all(r["origin"] == "admin" for r in created["created"])


def test_a_scenario_rotates_merchants_when_repeated(admin):
    names = [admin.post("/api/v1/admin/demo/scenarios/large_purchase").json()["created"][0]["merchant_display"] for _ in range(3)]
    assert len(set(names)) == 3
    assert code(admin.post("/api/v1/admin/demo/scenarios/unknown"), 422) == "invalid_request"


def test_log_records_each_change_newest_first(admin):
    admin.post("/api/v1/admin/demo/transactions", json=GOOD)
    admin.post("/api/v1/admin/demo/scenarios/duplicate")
    log = admin.get("/api/v1/admin/demo/log").json()
    assert [entry["action"] for entry in log[:2]] == ["scenario", "create"]
    assert all(len(entry["summary"]) <= 200 for entry in log)


def test_reset_restores_the_baseline_and_clears_decisions_and_local_memory(admin):
    admin.post("/api/v1/admin/demo/scenarios/duplicate")
    admin.post("/api/v1/admin/demo/transactions", json={**GOOD, "amount": 500, "category": "electronics"})
    alert = next(a for a in admin.get("/api/v1/alerts").json() if a["alert_type"] == "amount_anomaly")
    confirmed = admin.post(f"/api/v1/alerts/{alert['alert_id']}/confirmations",
                           json={"decision": "normal", "consent_to_memory": True}).json()
    assert confirmed["memory_status"] == "written" and len(admin.get("/api/v1/memories").json()) == 1
    result = admin.post("/api/v1/admin/demo/reset").json()
    assert result == {"restored": 18, "cleared_decisions": 1, "cleared_memories": 1}
    rows = admin.get("/api/v1/admin/demo/transactions").json()
    assert len(rows) == 18 and {r["origin"] for r in rows} == {"baseline"}
    alerts = admin.get("/api/v1/alerts").json()
    assert len(alerts) == 3 and {a["status"] for a in alerts} == {"open"}
    assert admin.get("/api/v1/memories").json() == []
    assert admin.get("/api/v1/admin/demo/log").json()[0]["action"] == "reset"


def test_reset_refuses_while_a_backboard_memory_exists(admin):
    admin.post("/api/v1/admin/demo/scenarios/large_purchase")
    with sqlite3.connect(admin.app.state.settings.database_path) as db:
        db.execute("INSERT INTO memories (memory_id,owner,summary,created_at,source,local_persisted) VALUES "
                   "('mem_remote','demo-user-001','x','2026-10-18T00:00:00+00:00','backboard',1)")
    assert code(admin.post("/api/v1/admin/demo/reset"), 409) == "remote_memory_exists"
    assert admin.get("/api/v1/admin/demo/status").json()["rows"] == 19  # nothing was touched


def test_admin_charges_reach_the_ai_payload_only_in_generalized_form(admin):
    row = admin.post("/api/v1/admin/demo/transactions", json={**GOOD, "merchant": "Secret Merchant Name", "amount": 777.77}).json()
    preview = admin.get(f"/api/v1/privacy/preview/{row['id']}").json()
    text = json.dumps(preview["safe_payload"])
    assert "Secret" not in text and "777" not in text and row["id"] not in text
    assert set(preview["safe_payload"]) == {"merchant_category", "amount_bucket", "currency", "local_day_part",
                                            "same_category_same_amount_24h_count", "is_subscription",
                                            "subscription_delta_bucket", "prior_user_confirmation"}


def test_edits_survive_a_restart(tmp_path):
    with make_client(tmp_path) as first:
        sign_in(first, "admin", ADMIN_PASS)
        created = first.post("/api/v1/admin/demo/transactions", json=GOOD).json()["id"]
    with make_client(tmp_path) as second:
        sign_in(second, "admin", ADMIN_PASS)
        ids = {r["id"] for r in second.get("/api/v1/admin/demo/transactions").json()}
        assert created in ids and len(ids) == 19


def test_demo_routes_are_local_json_only(admin):
    admin.headers["origin"] = "https://evil.example"
    assert admin.post("/api/v1/admin/demo/reset").status_code == 403
    admin.headers["origin"] = ORIGIN
    admin.headers["content-type"] = "text/plain"
    assert admin.post("/api/v1/admin/demo/transactions", content="x").status_code == 403


# ---------------------------------------------------------------- migration ----
OLD_SCHEMA = """
CREATE TABLE demo_transaction_sets (owner TEXT PRIMARY KEY, version TEXT NOT NULL);
CREATE TABLE demo_transactions (
    owner TEXT NOT NULL REFERENCES demo_transaction_sets(owner), id TEXT NOT NULL, occurred_at TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents>=0),
    currency TEXT NOT NULL CHECK(currency='USD'), direction TEXT NOT NULL CHECK(direction IN ('debit','credit')),
    merchant_display TEXT NOT NULL CHECK(length(merchant_display)<=80),
    merchant_category TEXT NOT NULL CHECK(length(merchant_category)<=40),
    source TEXT NOT NULL CHECK(source='synthetic'), account_token TEXT NOT NULL,
    is_subscription INTEGER NOT NULL CHECK(is_subscription IN (0,1)),
    kind TEXT NOT NULL DEFAULT 'purchase' CHECK(kind IN ('purchase','transfer','deposit','withdrawal')),
    PRIMARY KEY(owner,id));
INSERT INTO demo_transaction_sets VALUES ('demo-user-001','synthetic-v2');
INSERT INTO demo_transactions VALUES ('demo-user-001','txn_syn_old','2026-10-17T10:00:00-04:00',1234,'USD','debit',
    'Legacy Shop','other','synthetic','acct_demo_a1',0,'purchase');
"""


def columns(path):
    with sqlite3.connect(path) as db:
        return {r[1] for r in db.execute("PRAGMA table_info(demo_transactions)")}


def test_an_existing_database_is_migrated_in_place_with_one_backup(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.executescript(OLD_SCHEMA)
    assert "origin" not in columns(path)
    Store(path)
    assert {"origin", "edited_at"} <= columns(path)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        row = dict(db.execute("SELECT * FROM demo_transactions WHERE id='txn_syn_old'").fetchone())
    assert row["origin"] == "baseline" and row["edited_at"] is None and row["amount_cents"] == 1234
    backup = tmp_path / "old.pre-demo-edit.bak"
    assert backup.exists() and "origin" not in columns(backup)
    stamp = backup.stat().st_mtime_ns
    Store(path)
    Store(path)
    assert backup.stat().st_mtime_ns == stamp  # one backup, never overwritten by later starts
    # The migrated rows still load through the canonical path.
    assert [t.id for t in Store(path).list_transactions("demo-user-001")] == ["txn_syn_old"]


def test_a_fresh_database_needs_no_backup(tmp_path):
    path = tmp_path / "new.db"
    store = Store(path)
    load_transactions(store, "demo-user-001")
    Store(path)
    assert not list(tmp_path.glob("*.bak"))
    assert {"origin", "edited_at"} <= columns(path)


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/data-sources/banksim/transactions"),
    ("GET", "/api/v1/data-sources/nessie/transactions"),
    ("POST", "/api/v1/data-sources/nessie/refresh"),
])
def test_source_routes_share_the_admin_session_gate(anon, method, path):
    def call():
        return anon.request(method, path, **({"json": {}} if method == "POST" else {}))

    assert code(call(), 401) == "auth_required"
    assert sign_in(anon, "user", USER_PASS).status_code == 200
    assert code(call(), 403) == "admin_only"
    assert sign_in(anon, "admin", ADMIN_PASS).status_code == 200
    result = call()
    assert result.status_code == (200 if "banksim" in path else 503)
    assert anon.post("/api/v1/auth/logout", json={}).status_code == 200
    assert code(call(), 401) == "auth_required"


def test_demo_edit_and_reset_cannot_change_source_databases(admin):
    stores = admin.app.state.source_stores

    def snapshot():
        result = {}
        for name, store in stores.items():
            with store.connect() as db:
                result[name] = list(db.iterdump())
        return result

    before = snapshot()
    created = admin.post("/api/v1/admin/demo/transactions", json=GOOD).json()
    assert admin.patch(f"/api/v1/admin/demo/transactions/{created['id']}", json={"amount": 8.25}).status_code == 200
    assert admin.delete(f"/api/v1/admin/demo/transactions/{created['id']}").status_code == 204
    assert admin.post("/api/v1/admin/demo/scenarios/duplicate").status_code == 200
    assert admin.post("/api/v1/admin/demo/reset").status_code == 200
    assert snapshot() == before


@pytest.mark.parametrize("field", ["merchant", "category", "amount", "occurred_at", "direction", "is_subscription"])
def test_explicit_null_patch_is_rejected_without_changing_the_charge(admin, field):
    created = admin.post("/api/v1/admin/demo/transactions", json=GOOD).json()
    before = admin.get("/api/v1/admin/demo/transactions").json()
    response = admin.patch(f"/api/v1/admin/demo/transactions/{created['id']}", json={field: None})
    assert code(response, 422) == "invalid_request"
    assert admin.get("/api/v1/admin/demo/transactions").json() == before


@pytest.mark.parametrize("state", ["claimed", "preparing", "pending"])
def test_reset_preserves_unresolved_memory_intents_and_reconciliation(admin, state):
    store, owner, alert_id = admin.app.state.store, "demo-user-001", "alert_txn_syn_004"
    receipt, created = store.claim_confirmation(owner, alert_id, "normal", True, True, "test-request")
    assert created and receipt.memory_status == "pending"
    if state != "claimed":
        store.prepare_memory_job(owner, alert_id, "test-assistant", "Approved test category preference")
    if state == "pending":
        assert store.record_memory_baseline(owner, alert_id, {"existing-memory"})
    with store.connect() as db:
        before = list(db.iterdump())
    assert code(admin.post("/api/v1/admin/demo/reset"), 409) == "remote_memory_exists"
    with store.connect() as db:
        assert list(db.iterdump()) == before


def test_reset_succeeds_after_explicit_pending_memory_deletion(admin):
    store, owner, alert_id = admin.app.state.store, "demo-user-001", "alert_txn_syn_004"
    store.claim_confirmation(owner, alert_id, "normal", True, True, "test-request")
    local_id = store.prepare_memory_job(owner, alert_id, "test-assistant", "Approved test category preference")
    assert admin.delete(f"/api/v1/memories/{local_id}").status_code == 204
    assert store.memory_job(owner, alert_id=alert_id)["state"] == "deleted"
    assert admin.post("/api/v1/admin/demo/reset").status_code == 200
