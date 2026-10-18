import json
from collections import Counter

from app.adapters.account_demo import build_account_demo
from app.core.account_dataset import AccountDataset
from app.core.dataset_store import DatasetStore
from tests.unit.data.test_account_demo import inputs


def test_researched_probabilities_replace_cache_frequencies_across_18_accounts(tmp_path):
    csv_path, nessie_path = inputs(tmp_path)
    source = DatasetStore(nessie_path, 'nessie')
    base = source.list_transactions('owner-0')[0]
    source.upsert_transactions([base.model_copy(update={
        'id': f'template-{index}', 'source_record_key': f'template-{index}',
        'owner': f'owner-{index}', 'account_token': f'acct_{index:032x}'})
        for index in range(2, 18)])
    target = tmp_path / 'research-profile'
    build_account_demo(csv_path, nessie_path, target, tmp_path / 'labels')
    store = AccountDataset(target / 'nessie.db', 'nessie')
    accounts, count = store.accounts(limit=100)
    assert count == 18
    totals = Counter()
    per_account = Counter()
    for account in accounts:
        rows, total = store.account_page(account['account_token'], limit=100)
        assert total == len(rows) == 100
        counts = Counter(row.kind for row in rows)
        totals.update(counts)
        per_account[tuple(counts[k] for k in ('purchase', 'transfer', 'deposit', 'withdrawal'))] += 1
    assert totals == {'purchase': 1542, 'transfer': 96, 'deposit': 144, 'withdrawal': 18}
    assert per_account == {(86, 5, 8, 1): 12, (85, 6, 8, 1): 6}
    manifest = json.loads((target / 'manifest.json').read_text())
    assert manifest['inputs']['version'] == 'account-demo-v3'
    assert manifest['nessie_distribution']['profile_id'] == 'dcpc2025-restricted-four-kind-v1'
    assert manifest['nessie_distribution']['total_counts'] == dict(totals)


def test_seed_and_calibration_changes_isolate_owners_and_transaction_ids(tmp_path, monkeypatch):
    import app.adapters.account_demo as generator
    csv_path, nessie_path = inputs(tmp_path)
    codes = owners = ids = None
    for index, seed in enumerate((2026, 2027, 2027)):
        if index == 2:
            profile = json.loads(generator.PROFILE_PATH.read_text())
            profile['weighted_counts']['purchase'] = '16834.88430991768836231'
            path = tmp_path / 'changed-profile.json'
            path.write_text(json.dumps(profile))
            monkeypatch.setattr(generator, 'PROFILE_PATH', path)
        target = tmp_path / f'batch-{index}'
        generator.build_account_demo(csv_path, nessie_path, target, tmp_path / f'labels-{index}', seed=seed)
        store = AccountDataset(target / 'nessie.db', 'nessie')
        with store.connect() as db:
            current_codes = {row[0] for row in db.execute('SELECT account_token FROM accounts')}
            current_owners = {row[0] for row in db.execute('SELECT owner FROM accounts')}
            current_ids = {row[0] for row in db.execute('SELECT id FROM transactions')}
        if codes is not None:
            assert codes == current_codes
            assert owners.isdisjoint(current_owners) and ids.isdisjoint(current_ids)
        codes, owners, ids = current_codes, current_owners, current_ids
