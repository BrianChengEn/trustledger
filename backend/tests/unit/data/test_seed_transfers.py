import hashlib

import httpx
import pytest

from app.adapters.nessie import API_BASE, NessieClient
from app.adapters.nessie_fixture import BASELINE_SHA256
from app.adapters.seed_nessie import SeedBlocked, seed_transfers
from app.adapters.synthetic_dataset import identifier
from app.core.config import Settings
from app.core.store import Store


@pytest.fixture
def sandbox(tmp_path):
    store = Store(tmp_path / 'transfers.db')
    settings = Settings(_env_file=None, database_path=store.filename,
                        transaction_provider='nessie', nessie_api_key='transfer-test')
    scope = hashlib.sha256(b'transfer-test').hexdigest()
    customer, accounts = 'c' * 24, ['a' * 24, 'b' * 24]
    with store.connect() as db:
        run = db.execute("INSERT INTO seed_runs(owner,dataset_sha256,api_base_url,credential_fingerprint,"
                         "state,created_at,updated_at) VALUES(?,?,?,?,'complete','now','now')",
                         (settings.demo_user_id, BASELINE_SHA256, API_BASE, scope)).lastrowid
        db.execute("INSERT INTO seed_records(run_id,kind,local_id,remote_id,request_fingerprint,state,updated_at) "
                   "VALUES(?,'customer',?,?,'test','confirmed','now')", (run, identifier('c', 1), customer))
        for number, account in enumerate(accounts, 1):
            db.execute("INSERT INTO seed_records(run_id,kind,local_id,parent_kind,parent_local_id,remote_id,"
                       "request_fingerprint,state,updated_at) VALUES(?,'account',?,'customer',?,?,'test','confirmed','now')",
                       (run, identifier('a', number), identifier('c', 1), account))
    state = {'rows': {accounts[0]: [{'id': 'd' * 24, 'amount': 9, 'status': 'pending',
                                    'transaction_date': '2026-10-17', 'description': 'existing'}]},
             'posts': 0, 'lose_write': False, 'lose_ack': False, 'reject': False, 'truncate_amounts': False}

    def upstream(request):
        if request.url.path == '/accounts':
            return httpx.Response(200, json=[{'_id': account, 'customer_id': customer}
                                            for account in accounts])
        account = request.url.path.split('/')[2]
        if request.method == 'POST':
            import json
            with store.connect() as db:
                assert db.execute("SELECT 1 FROM nessie_setup_operations WHERE state='pending'").fetchone()
            state['posts'] += 1
            if state['reject']:
                return httpx.Response(400, json={'private': 'rejected'})
            if not state['lose_write']:
                payload = json.loads(request.content)
                if state['truncate_amounts']:
                    payload['amount'] = int(payload['amount'])
                state['rows'].setdefault(account, []).append({
                    'id': f"{state['posts']:024x}", **payload})
            if state['lose_write'] or state['lose_ack']:
                raise httpx.ReadTimeout('private request URL must not be exposed')
            return httpx.Response(201, json={})
        return (httpx.Response(200, json=state['rows'][account]) if account in state['rows']
                else httpx.Response(404))

    client = NessieClient('transfer-test', transport=httpx.MockTransport(upstream))
    return settings, store, client, state


def test_explicit_transfer_setup_tops_up_all_confirmed_accounts_without_duplicates(sandbox):
    settings, store, client, state = sandbox
    result = seed_transfers(settings, store, client)
    assert result == {'accounts': 2, 'transfers': 20, 'created': 19}
    assert state['posts'] == 19
    assert state['rows']['a' * 24][0]['description'] == 'existing'
    assert seed_transfers(settings, Store(store.filename), client)['created'] == 0
    assert state['posts'] == 19


@pytest.mark.parametrize('failure', ['lose_write', 'reject'])
def test_uncertain_or_rejected_transfer_is_never_automatically_reposted(sandbox, failure):
    settings, store, client, state = sandbox
    state[failure] = True
    for _ in range(2):
        with pytest.raises(SeedBlocked):
            seed_transfers(settings, store, client)
    assert state['posts'] == 1


def test_lost_transfer_ack_is_reconciled_by_readback(sandbox):
    settings, store, client, state = sandbox
    state['lose_ack'] = True
    assert seed_transfers(settings, store, client)['transfers'] == 20
    assert state['posts'] == 19


def test_transfer_setup_preserves_amounts_with_integer_only_provider(sandbox):
    settings, store, client, state = sandbox
    state['truncate_amounts'] = True
    assert seed_transfers(settings, store, client)['transfers'] == 20
    assert seed_transfers(settings, store, client)['created'] == 0


def test_transfer_setup_rejects_unconfirmed_accounts_before_post(sandbox):
    settings, store, _, state = sandbox
    client = NessieClient('transfer-test', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=[{'_id': 'f' * 24, 'customer_id': 'c' * 24}])))
    with pytest.raises(SeedBlocked, match='confirmed baseline'):
        seed_transfers(settings, store, client)
    assert state['posts'] == 0


def test_transfer_setup_rejects_invalid_existing_rows_before_post(sandbox):
    settings, store, client, state = sandbox
    state['rows']['a' * 24][0]['amount'] = 0.001
    with pytest.raises(SeedBlocked, match='validation'):
        seed_transfers(settings, store, client)
    assert state['posts'] == 0


@pytest.mark.parametrize('change', [{'transaction_provider': 'synthetic'},
                                   {'nessie_api_key': Settings(_env_file=None, nessie_api_key='changed').nessie_api_key}])
def test_transfer_setup_requires_selected_provider_and_matching_credential(sandbox, change):
    settings, store, client, state = sandbox
    with pytest.raises(SeedBlocked):
        seed_transfers(settings.model_copy(update=change), store, client)
    assert state['posts'] == 0
