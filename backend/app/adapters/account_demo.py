"""Explicit offline allocation. Labels never enter runtime SQLite."""
import hashlib
import json
import random
import re
import shutil
import sqlite3
import tempfile
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

from app.adapters.dataset_import import banksim_rows, local_token
from app.core.account_dataset import AccountDataset
from app.core.dataset_store import DatasetStore

VERSION = 'account-demo-v3'
RATE = Fraction(7200, 594643)
KINDS = ('purchase', 'transfer', 'deposit', 'withdrawal')
SYNTHETIC_KINDS = 'nessie-synthetic-kinds-v1'
PROFILE_PATH = Path(__file__).resolve().parents[3] / 'fixtures/dcpc2025-kind-profile.json'


def digest(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def quota(accounts):
    return round(100 * accounts * RATE)


def kind_quotas(counts):
    weights = {kind: Fraction(96 * counts[kind], sum(counts.values())) for kind in KINDS}
    result = {kind: 1 + int(weight) for kind, weight in weights.items()}
    for kind in sorted(KINDS, key=lambda kind: (-(weights[kind] % 1), kind))[:100 - sum(result.values())]:
        result[kind] += 1
    return result


def research_kind_quotas(codes, seed):
    profile = json.loads(PROFILE_PATH.read_text())
    weights = {kind: Fraction(value) for kind, value in profile['weighted_counts'].items()}
    if set(weights) != set(KINDS) or any(value <= 0 for value in weights.values()) or not codes:
        raise ValueError('Invalid research type profile or account population.')
    scale = sum(weights.values())
    exact = {kind: 100 * len(codes) * weights[kind] / scale for kind in KINDS}
    totals = {kind: int(value) for kind, value in exact.items()}
    for kind in sorted(KINDS, key=lambda kind: (-(exact[kind] % 1), kind))[:100 * len(codes) - sum(totals.values())]:
        totals[kind] += 1
    base = {kind: int(100 * weights[kind] / scale) for kind in KINDS}
    result = {code: dict(base) for code in codes}
    order = random.Random(seed).sample(sorted(codes), len(codes))
    slot = 0
    for kind in sorted(KINDS, key=lambda kind: (-(100 * weights[kind] / scale % 1), kind)):
        for _ in range(totals[kind] - base[kind] * len(codes)):
            result[order[slot % len(codes)]][kind] += 1
            slot += 1
    if any(sum(counts.values()) != 100 for counts in result.values()):
        raise ValueError('Research type allocation is incomplete.')
    return profile, result


def build_account_demo(csv_path, nessie_path, output_dir, labels_dir, *, seed=2026):
    csv_path, nessie_path = Path(csv_path).resolve(), Path(nessie_path).resolve()
    output_dir, labels_dir = Path(output_dir).resolve(), Path(labels_dir).resolve()
    if (labels_dir.is_relative_to(output_dir) or output_dir.is_relative_to(labels_dir)
            or any(path.is_relative_to(output_dir) or path.is_relative_to(labels_dir)
                   for path in (csv_path, nessie_path))):
        raise ValueError('Inputs, runtime output and offline labels must be separate.')
    inputs = {'banksim': digest(csv_path), 'nessie': digest(nessie_path), 'seed': seed, 'version': VERSION,
              'kind_profile_sha256': digest(PROFILE_PATH)}
    signature = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    if output_dir.exists():
        manifest = json.loads((output_dir / 'manifest.json').read_text())
        if manifest['inputs'] != inputs:
            raise ValueError('Existing allocation has different inputs; choose a new output directory.')
        for source in ('banksim', 'nessie'):
            if (digest(output_dir / f'{source}.db') != manifest['database_digests'][source]
                    or digest(labels_dir / f'{source}.jsonl') != manifest['label_digests'][source]):
                raise ValueError('Existing allocation no longer matches its manifest.')
        return manifest['report']
    if labels_dir.exists():
        label_manifest = labels_dir / 'manifest.json'
        if not label_manifest.is_file():
            raise ValueError('Offline label directory already exists without a matching manifest.')
        previous = json.loads(label_manifest.read_text())
        if (previous['inputs'] != inputs or any(
                digest(labels_dir / f'{source}.jsonl') != previous['label_digests'][source]
                for source in ('banksim', 'nessie'))):
            raise ValueError('Existing offline labels do not match these inputs.')
    dataset = 'banksim:' + inputs['banksim']
    customers = Counter()
    bank_positives = 0
    for row, positive in banksim_rows(csv_path, dataset):
        customers[row.customer_token] += 1
        bank_positives += positive
    if not customers:
        raise ValueError('BankSim has no customers.')
    with sqlite3.connect(nessie_path.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        source = db.execute('SELECT source FROM source_metadata WHERE singleton=1').fetchone()
        if source is None or source['source'] != 'nessie':
            raise ValueError('Expected a normalized Nessie source database.')
        groups = defaultdict(list)
        for row in DatasetStore._records(db, db.execute('SELECT * FROM transactions ORDER BY owner,id')):
            if (row.source != 'nessie' or row.kind not in KINDS
                    or not re.fullmatch(r'acct_[0-9a-f]{32}', row.account_token or '')):
                raise ValueError('Nessie templates require a local account and Nessie provenance.')
            groups[row.account_token].append(row)
        if not groups or any(len({row.owner for row in rows}) != 1 for rows in groups.values()):
            raise ValueError('Nessie account ownership is missing or ambiguous.')
    source_counts = Counter(row.kind for rows in groups.values() for row in rows)
    profile, account_type_counts = research_kind_quotas(sorted(groups), seed)
    synthetic_counts = {kind: sum(not any(row.kind == kind for row in rows) for rows in groups.values())
                        for kind in KINDS}
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    labels_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.account-demo-', dir=output_dir.parent))
    label_stage = Path(tempfile.mkdtemp(prefix='.account-labels-', dir=labels_dir.parent))
    rng = random.Random(seed)
    report = {}
    for source in ('banksim', 'nessie'):
        codes = ([local_token('acct_', dataset, customer) for customer in sorted(customers)]
                 if source == 'banksim' else sorted(groups))
        bindings = dict(zip(codes, sorted(customers))) if source == 'banksim' else {
            code: groups[code][0].owner for code in codes}
        accounts = [(code, f'{VERSION}:{signature}:{source}:{code}', f'{source.title()} account {i:04d}', bindings[code])
                    for i, code in enumerate(codes, 1)]
        two = set(rng.sample(codes, quota(len(codes)) - len(codes))) if source == 'nessie' else set()
        generated = []
        if source == 'nessie':
            for account in accounts:
                positive_slots = set(rng.sample(range(100), 2 if account[0] in two else 1))
                templates = {kind: [row for row in groups[account[0]] if row.kind == kind] for kind in KINDS}
                for kind in KINDS:
                    if not templates[kind]:
                        base = groups[account[0]][0]
                        templates[kind] = [base.model_copy(update={
                            'id': local_token('template_', SYNTHETIC_KINDS, account[0] + ':' + kind),
                            'dataset_id': SYNTHETIC_KINDS, 'source_record_key': account[0] + ':' + kind,
                            'kind': kind, 'direction': 'credit' if kind == 'deposit' else
                            'unknown' if kind == 'transfer' else 'debit',
                            'merchant_token': None, 'merchant_display': None, 'merchant_category': None,
                            'source_category': None, 'is_subscription': None})]
                kinds = [kind for kind, count in account_type_counts[account[0]].items() for _ in range(count)]
                rng.shuffle(kinds)
                for slot, kind in enumerate(kinds):
                    positive = slot in positive_slots
                    generated.append((rng.choice(templates[kind]), positive, account, slot))

        def cases():
            if source == 'nessie':
                yield from generated
            else:
                by_customer = {account[3]: account for account in accounts}
                for row, positive in banksim_rows(csv_path, dataset):
                    yield row, positive, by_customer[row.customer_token], row.source_record_key

        store = AccountDataset(stage / f'{source}.db', source)
        positive_count = 0
        with (label_stage / f'{source}.jsonl').open('w', encoding='utf-8') as labels, store.connect() as db:
            db.executemany('INSERT INTO accounts VALUES(?,?,?,?)', accounts)

            def records():
                nonlocal positive_count
                for original, positive, account, slot in cases():
                    code, owner, _, _ = account
                    if source == 'banksim':
                        row = original.model_copy(update={'owner': owner, 'account_token': code})
                    else:
                        key = f'{slot:03d}'
                        row = original.model_copy(update={
                            'id': local_token('txn_', signature, code + ':' + key), 'owner': owner,
                            'dataset_id': VERSION + ':' + signature, 'source_record_key': key,
                            'account_token': code})
                    yield row
                    db.execute('INSERT INTO account_origins VALUES(?,?,?,?,?)',
                               (owner, row.id, original.dataset_id, original.source_record_key, original.owner))
                    labels.write(json.dumps({'id': row.id, 'account_token': code, 'fraud': positive,
                                             'label_origin': ('banksim-ground-truth' if source == 'banksim'
                                                              else 'simulated-allocation')}) + '\n')
                    positive_count += positive

            written = store._upsert(db, records())
            sizes = dict(db.execute('SELECT owner,count(*) FROM transactions GROUP BY owner'))
            expected = {account[1]: customers[account[3]] if source == 'banksim' else 100
                        for account in accounts}
            positives = bank_positives if source == 'banksim' else quota(len(accounts))
            if (written != sum(expected.values()) or sizes != expected
                    or positive_count != positives or db.execute('PRAGMA foreign_key_check').fetchall()):
                raise ValueError('Allocation verification failed.')
        report[source] = {'accounts': len(accounts), 'transactions': written, 'fraud_samples': positive_count}
    if (digest(csv_path) != inputs['banksim'] or digest(nessie_path) != inputs['nessie']
            or digest(PROFILE_PATH) != inputs['kind_profile_sha256']):
        raise ValueError('Source or calibration changed during generation; no batch was published.')
    manifest = {'inputs': inputs, 'report': report,
                'nessie_distribution': {'method': 'survey-weighted-largest-remainder-v1',
                                        'profile_id': profile['id'],
                                        'source_counts': {kind: source_counts[kind] for kind in KINDS},
                                        'total_counts': {kind: sum(counts[kind] for counts in account_type_counts.values())
                                                         for kind in KINDS},
                                        'per_account_counts': account_type_counts,
                                        'synthetic_template_counts': synthetic_counts},
                'database_digests': {s: digest(stage / f'{s}.db') for s in report},
                'label_digests': {s: digest(label_stage / f'{s}.jsonl') for s in report}}
    (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    (label_stage / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    if labels_dir.exists():
        if any(digest(labels_dir / f'{source}.jsonl') != manifest['label_digests'][source]
               for source in ('banksim', 'nessie')):
            raise ValueError('Recovered offline labels differ from the regenerated allocation.')
        shutil.rmtree(label_stage)
    else:
        label_stage.rename(labels_dir)
    stage.rename(output_dir)
    return report
