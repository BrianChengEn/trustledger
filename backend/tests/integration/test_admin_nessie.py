from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import runpy
import sqlite3
import re
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.nessie import NessieClient, QUERIES
from app.core.config import Settings
from app.core.store import Store
from app.main import create_app

PREFIX = "/api/v1/admin/nessie"
ORIGIN = {"origin": "http://localhost:5173"}
CUSTOMER = "c" * 24
ACCOUNT = "a" * 24
SCOPE = hashlib.sha256(b"sentinel").hexdigest()


@pytest.fixture
def admin(tmp_path):
    settings = Settings(_env_file=None, database_path=tmp_path / "db", nessie_api_key="sentinel",
                        backboard_api_key="", jev_api_key="")
    app = create_app(settings)
    calls = []

    def upstream(request):
        calls.append(request.url.path)
        if request.url.path == "/customers":
            body = [{"_id": CUSTOMER, "first_name": "PRIVATE NAME", "address": {"city": "PRIVATE CITY"}}]
        elif request.url.path.endswith(("/deposits", "/withdrawals", "/purchases", "/transfers")):
            body = [{"_id": "d" * 24, "amount": 123, "status": "completed", "medium": "balance",
                     "description": "PRIVATE DESCRIPTION", "transaction_date": "2026-10-17"}]
        else:
            row = {"_id": ACCOUNT, "customer_id": CUSTOMER, "account_number": "PRIVATE ACCOUNT",
                   "nickname": "PRIVATE NICKNAME", "type": "Checking", "balance": 100, "rewards": 1}
            body = row if request.url.path == "/accounts/" + ACCOUNT else [row]
        return httpx.Response(200, json=body)

    app.state.nessie = NessieClient("sentinel", transport=httpx.MockTransport(upstream))
    with TestClient(app, base_url="http://127.0.0.1", headers=ORIGIN) as client:
        yield client, calls


def local_codes(client):
    customer = client.post(PREFIX + "/query", json={"query": "customers.list"}).json()
    account = client.post(PREFIX + "/query", json={"query": "accounts.list"}).json()
    return customer["response_body"][0]["resource_id"], account["response_body"][0]["resource_id"]


def capture():
    return {"source": "synthetic", "query": "accounts.list",
            "requested_at": datetime.now(timezone.utc).isoformat(), "duration_ms": 1,
            "http_status": 200, "transport_error": None,
            "response_body": "PRIVATE BODY", "resource_id": ACCOUNT}


def test_eight_queries_use_local_codes_and_never_expose_or_store_raw_data(admin):
    client, calls = admin
    customer, account = local_codes(client)
    assert customer.startswith("customer_") and account.startswith("acct_")
    for query in QUERIES:
        body = {"query": query}
        if "{id}" in QUERIES[query]:
            body["resource_id"] = customer if query == "accounts.by_customer" else account
        for _ in range(2):
            response = client.post(PREFIX + "/query", json=body)
            assert response.status_code == 200
            saved = response.json()
            assert saved["http_status"] == 200 and saved["write_status"] == "saved"
            assert "PRIVATE" not in response.text and ACCOUNT not in response.text and CUSTOMER not in response.text
            history = client.get(PREFIX + "/history/" + str(saved["history_id"])).json()
            assert not {"resource_id", "response_body", "body_format"} & history.keys()
    assert len(calls) == 2 + len(QUERIES) * 4
    assert "/accounts/" + ACCOUNT in calls
    assert "/customers/" + CUSTOMER + "/accounts" in calls
    assert "PRIVATE" not in json.dumps(client.get(PREFIX + "/resources").json())
    assert "PRIVATE" not in client.app.state.store.filename.read_bytes().decode(errors="ignore")
    with client.app.state.store.connect() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(query_history)")}
    assert not {"resource_id", "response_body", "body_format"} & columns
    assert client.post(PREFIX + "/compare", json={"left_id": 1, "right_id": 2}).status_code == 404


@pytest.mark.parametrize('query', ['purchases.by_account', 'transfers.by_account'])
def test_purchase_transfer_queries_persist_only_typed_projection(admin, query):
    client, _ = admin
    _, account = local_codes(client)
    response = client.post(PREFIX + '/query', json={'query': query, 'resource_id': account})
    assert response.status_code == 200
    assert response.json()['response_body'] == [{'medium': 'balance', 'status': 'completed', 'amount': 123}]
    with client.app.state.store.connect() as db:
        row = db.execute('SELECT amount_cents,resource_code FROM admin_query_rows '
                         'WHERE query_name=?', (query,)).fetchone()
    assert row['amount_cents'] == 12300 and row['resource_code'] == account
    assert 'PRIVATE' not in client.app.state.store.filename.read_bytes().decode(errors='ignore')


def test_failed_nessie_prerequisite_does_not_delete_history(admin):
    client, _ = admin
    client.post(PREFIX + '/query', json={'query': 'customers.list'}).raise_for_status()
    store = client.app.state.store
    before = store.list_history('demo-user-001')
    client.app.state.nessie = NessieClient('sentinel', transport=httpx.MockTransport(
        lambda request: httpx.Response(503)))
    response = client.request('DELETE', PREFIX + '/history', json={'confirm': True})
    assert response.status_code == 502
    assert store.list_history('demo-user-001') == before


def test_query_cache_failure_preserves_previous_rows_and_hides_unpersisted_body(admin):
    client, _ = admin
    local_codes(client)
    with client.app.state.store.connect() as db:
        before = [tuple(row) for row in db.execute('SELECT * FROM admin_query_rows')]
        db.execute("CREATE TRIGGER fail_cache BEFORE INSERT ON admin_query_rows "
                   "BEGIN SELECT RAISE(ABORT, 'private cache error'); END")
    response = client.post(PREFIX + '/query', json={'query': 'accounts.list'})
    result = response.json()
    assert result['write_status'] == 'failed' and result['response_body'] is None
    assert result['body_format'] == 'none' and 'private cache error' not in response.text
    with client.app.state.store.connect() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM admin_query_rows')] == before


def test_v011_sqlite_upgrade_preserves_movements_memory_and_history_sequence(admin):
    client, _ = admin
    store = client.app.state.store
    customer, _ = local_codes(client)
    owner = 'demo-user-001:nessie:' + SCOPE + ':' + customer
    store.save_workspace_collection(owner, '', 'accounts', [('acct_test', 'Checking', 100, 0)],
                                    '2026-10-17', 200, None)
    store.save_workspace_collection(owner, 'acct_test', 'withdrawals',
                                    [('txn_test', 'acct_test', 'withdrawal', '2026-10-17T00:00:00Z',
                                      1, 100, 'debit', 'completed')], '2026-10-17', 200, None)
    before = store.workspace_rows(owner)
    store.confirm(owner, 'migration-alert', 'normal', True, 'Sanitized category fact', 'test')
    with store.connect() as db:
        for table in ['workspace_movements', 'query_history']:
            schema = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()[0]
            legacy = schema.replace(", 'unknown'", '').replace(",'unknown'", '')
            legacy = re.sub(r",\s*'purchases.by_account','transfers.by_account'", '', legacy)
            db.execute('ALTER TABLE ' + table + ' RENAME TO legacy_fixture')
            db.execute(legacy)
            db.execute('INSERT INTO ' + table + ' SELECT * FROM legacy_fixture')
            db.execute('DROP TABLE legacy_fixture')
        db.execute("UPDATE sqlite_sequence SET seq=100 WHERE name='query_history'")
    restarted = Store(store.filename)
    assert restarted.workspace_rows(owner) == before
    assert restarted.status(owner, 'migration-alert') == 'normal'
    assert len(restarted.list_memories(owner)) == 1
    record = {**capture(), 'query': 'transfers.by_account'}
    assert restarted.append_history('demo-user-001', record) > 100
    with restarted.connect() as db:
        assert db.execute("SELECT count(*) FROM sqlite_sequence WHERE name='query_history'").fetchone()[0] == 1


def test_raw_ids_unknown_codes_and_extra_input_never_execute(admin):
    client, calls = admin
    for body in [{"query": "invalid"}, {"query": "accounts.get"},
                 {"query": "accounts.get", "resource_id": ACCOUNT},
                 {"query": "accounts.get", "resource_id": "01234567-89ab-cdef-0123-456789abcdef"},
                 {"query": "accounts.get", "resource_id": "../private"},
                 {"query": "accounts.list", "resource_id": "account_" + "0" * 32},
                 {"query": "accounts.list", "key": "private-input"}]:
        result = client.post(PREFIX + "/query", json=body)
        assert result.status_code == 422
        assert "private-input" not in result.text
    assert client.post(PREFIX + "/query", json={"query": "accounts.get",
                       "resource_id": "account_" + "0" * 32}).status_code == 404
    assert calls == []


def test_aliases_are_owner_and_credential_scoped_and_accept_backend_uuid(admin):
    client, calls = admin
    store = client.app.state.store
    remote_id = "01234567-89ab-cdef-0123-456789abcdef"
    code = store.alias_resources("demo-user-001", SCOPE, "account", [remote_id])[remote_id]
    result = client.post(PREFIX + "/query", json={"query": "accounts.get", "resource_id": code})
    assert result.status_code == 200 and calls == ["/accounts/" + remote_id]
    assert remote_id not in result.text
    assert store.resolve_resource("other", SCOPE, code) is None
    client.app.state.settings.nessie_api_key = Settings(_env_file=None, nessie_api_key="changed").nessie_api_key
    refreshed = client.get(PREFIX + "/resources").json()
    assert all(row['resource_id'] != code for row in refreshed)
    assert store.resolve_resource('demo-user-001', hashlib.sha256(b'changed').hexdigest(), code) is None
    assert client.post(PREFIX + "/query", json={"query": "accounts.get", "resource_id": code}).status_code == 404
    assert len(calls) == 3


def test_history_write_failure_preserves_only_persisted_safe_projection(admin):
    client, calls = admin
    with client.app.state.store.connect() as db:
        db.execute("CREATE TRIGGER fail_history AFTER INSERT ON query_history "
                   "BEGIN SELECT RAISE(FAIL, 'private SQL'); END")
    response = client.post(PREFIX + "/query", json={"query": "accounts.list"})
    result = response.json()
    assert result["http_status"] == 200 and result["response_body"]
    assert result["history_id"] is None and result["write_status"] == "failed"
    assert result["write_label"] == "failed to write"
    assert "PRIVATE" not in response.text and "private SQL" not in response.text
    assert client.get(PREFIX + "/history").json()["items"] == []
    assert len(calls) == 2


def test_loopback_origin_json_and_configuration_guards(admin):
    client, calls = admin
    path, body = PREFIX + "/query", {"query": "accounts.list"}
    assert client.post(path, json=body, headers={"host": "remote.example"}).status_code == 403
    assert client.post(path, json=body, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post(path, content='{}', headers={"content-type": "text/plain"}).status_code == 403
    client.headers.pop("origin")
    assert client.post(path, json=body).status_code == 403
    client.headers.update(ORIGIN)
    client.app.state.settings.nessie_api_key = ""
    assert client.post(path, json=body).status_code == 503
    assert calls == []


@pytest.mark.parametrize("status,body", [(200, []), (401, "PRIVATE FAILURE"),
                                        (404, {"error": "PRIVATE MISSING"}), (500, "PRIVATE ERROR")])
def test_captured_status_matches_contract_without_leaking_error_bodies(admin, status, body):
    import yaml
    from jsonschema import Draft202012Validator

    client, _ = admin
    client.app.state.nessie = NessieClient("sentinel", transport=httpx.MockTransport(
        lambda _: httpx.Response(status, json=body)))
    response = client.post(PREFIX + "/query", json={"query": "customers.list"})
    result = response.json()
    assert result["http_status"] == status
    assert "PRIVATE" not in response.text
    contract = yaml.safe_load((Path(__file__).resolve().parents[3] /
                               "contracts/internal-api.openapi.yaml").read_text())
    schema = {"$ref": "#/components/schemas/AdminExecution", "components": contract["components"]}
    Draft202012Validator(schema).validate(result)


def test_metadata_paging_restart_delete_owner_and_stale_ids(admin):
    client, calls = admin
    store, owner = client.app.state.store, client.app.state.settings.demo_user_id
    ids = [store.append_history(owner, capture()) for _ in range(55)]
    foreign = store.append_history("another", capture())
    first = client.get(PREFIX + "/history").json()
    assert len(first["items"]) == 50
    second = client.get(PREFIX + "/history", params={"before_id": first["next_cursor"]}).json()
    assert [r["history_id"] for r in first["items"] + second["items"]] == ids[::-1]
    assert second["next_cursor"] is None
    saved = client.get(PREFIX + f"/history/{ids[0]}").json()
    with TestClient(create_app(client.app.state.settings), base_url="http://localhost", headers=ORIGIN) as restarted:
        restarted.app.state.nessie = client.app.state.nessie
        assert restarted.get(PREFIX + f"/history/{ids[0]}").json() == saved
    assert not {"response_body", "resource_id", "body_format"} & saved.keys()
    assert client.request("DELETE", PREFIX + "/history", json={}).status_code == 422
    assert client.request("DELETE", PREFIX + "/history", json={"confirm": False}).status_code == 422
    assert client.request("DELETE", PREFIX + f"/history/{foreign}", json={"confirm": True}).status_code == 404
    assert client.request("DELETE", PREFIX + "/history", json={"confirm": True}).json() == {"deleted": 55}
    assert client.get(PREFIX + f"/history/{ids[0]}").status_code == 404
    assert store.append_history(owner, capture()) > foreign
    assert store.get_history("another", foreign) is not None
    assert calls and all(path == '/customers' for path in calls)


def test_legacy_raw_history_is_purged_without_losing_metadata_or_sequence(tmp_path):
    store = Store(tmp_path / "legacy.db")
    store.confirm("owner", "alert", "normal", True, "Sanitized category fact", "test")
    with store.connect() as db:
        db.execute("DROP TABLE query_history")
        db.execute("CREATE TABLE query_history (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT,"
                   "source TEXT,query_name TEXT,requested_at TEXT,http_status INTEGER,duration_ms INTEGER,"
                   "transport_error TEXT,resource_id TEXT,response_body TEXT,body_format TEXT)")
        for _ in range(2):
            db.execute("INSERT INTO query_history VALUES(NULL,'owner','nessie','accounts.get',"
                       "'2026-10-17',200,1,NULL,?,'LEGACY_PRIVATE_BODY','json')", (ACCOUNT,))
        db.execute("DELETE FROM query_history WHERE id=2")
    restarted = Store(store.filename)
    record = restarted.get_history("owner", 1)
    assert record["http_status"] == 200
    assert not {"resource_id", "response_body", "body_format"} & record.keys()
    assert b"LEGACY_PRIVATE_BODY" not in store.filename.read_bytes()
    assert ACCOUNT.encode() not in store.filename.read_bytes()
    assert restarted.append_history("owner", capture()) > 2
    assert restarted.status("owner", "alert") == "normal"
    assert len(restarted.list_memories("owner")) == 1


def test_browser_server_never_uses_ambient_ai_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "browser.db"))
    monkeypatch.setenv("BACKBOARD_API_KEY", "synthetic-ambient-key")
    calls = []

    async def unexpected_provider(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Browser tests must not call AI providers")

    monkeypatch.setattr("app.services.ai.decision.classify", unexpected_provider)
    server = runpy.run_path(str(Path(__file__).parents[1] / "admin_console_server.py"))
    with TestClient(server["app"]) as browser:
        assert browser.post('/api/v1/workspace/refresh', json={}).status_code == 200
        response = browser.get("/api/v1/alerts")
        assert response.status_code == 200 and len(response.json()) == 3
    assert calls == []


def test_locked_privacy_cleanup_is_retried_until_raw_wal_is_removed(monkeypatch, tmp_path):
    store = Store(tmp_path / "locked.db")
    with store.connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("DROP TABLE query_history")
        db.execute("CREATE TABLE query_history (id INTEGER PRIMARY KEY AUTOINCREMENT,owner TEXT,"
                   "source TEXT,query_name TEXT,requested_at TEXT,http_status INTEGER,duration_ms INTEGER,"
                   "transport_error TEXT,response_body TEXT)")
        db.execute("INSERT INTO query_history VALUES(1,'owner','nessie','accounts.list',"
                   "'2026-10-17',200,1,NULL,'RAW_WAL_SENTINEL')")
    original = Store.connect

    @contextmanager
    def quick_connect(instance, **kwargs):
        with original(instance, **kwargs) as connection:
            connection.execute("PRAGMA busy_timeout=1")
            yield connection

    monkeypatch.setattr(Store, "connect", quick_connect)
    reader_context = original(store)
    reader = reader_context.__enter__()
    reader.execute("BEGIN")
    reader.execute("SELECT response_body FROM query_history").fetchall()
    try:
        with pytest.raises(sqlite3.OperationalError):
            Store(store.filename)
        with pytest.raises(sqlite3.OperationalError):
            Store(store.filename)
    finally:
        reader_context.__exit__(None, None, None)
    restarted = Store(store.filename)
    assert restarted.get_history("owner", 1)["http_status"] == 200
    for path in tmp_path.glob("locked.db*"):
        assert b"RAW_WAL_SENTINEL" not in path.read_bytes()
