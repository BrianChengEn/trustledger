"""Offline imports into source databases; no vendor calls or stored fraud labels."""
import csv
import hashlib
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.core.dataset_store import DatasetStore
from app.schemas.dataset import BankSimFeatures, TransactionRecord

HEADER = ['step', 'customer', 'age', 'gender', 'zipcodeOri', 'merchant',
          'zipMerchant', 'category', 'amount', 'fraud']


def local_token(prefix, dataset, value):
    return prefix + hashlib.sha256((dataset + ':' + value).encode()).hexdigest()[:32]


def banksim_rows(filename: Path, dataset: str):
    with Path(filename).open(newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != HEADER:
            raise ValueError('Unexpected BankSim header.')
        for number, raw in enumerate(reader, 1):
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError('Invalid BankSim row width.')
            values = {key: value.strip().strip("'") for key, value in raw.items()}
            if values['fraud'] not in {'0', '1'}:
                raise ValueError('Invalid BankSim label.')
            amount = Decimal(values['amount']) * 100
            if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
                raise ValueError('BankSim amount must have exact hundredths.')
            customer, merchant = values['customer'], values['merchant']
            customer_token = local_token('customer_', dataset, customer)
            key = f'{number:012d}'
            row = TransactionRecord(
                id=local_token('txn_', dataset, key), owner=customer_token,
                source='banksim', dataset_id=dataset, source_record_key=key,
                customer_token=customer_token, amount_minor=int(amount), currency='EUR',
                merchant_token=local_token('merchant_', dataset, merchant),
                source_category=values['category'], simulation_step=int(values['step']),
                banksim_features=BankSimFeatures(
                    customer_code=customer, merchant_code=merchant,
                    age_band=values['age'] or None, gender=values['gender'] or None,
                    zipcode_origin=values['zipcodeOri'] or None,
                    zipcode_merchant=values['zipMerchant'] or None))
            yield row, bool(int(values['fraud']))


def import_banksim(filename: Path, store: DatasetStore):
    if store.source != 'banksim' or Path(filename).resolve() == store.filename.resolve():
        raise ValueError('BankSim import requires a separate banksim source database.')
    with Path(filename).open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    dataset = 'banksim:' + digest
    labels = 0

    def records():
        nonlocal labels
        for row, label in banksim_rows(filename, dataset):
            labels += label
            yield row

    count = store.upsert_transactions(records())
    return {'dataset_id': dataset, 'transactions': count, 'fraud_labels': labels,
            'source_mode': 'offline-research'}


def import_nessie_cache(filename: Path, store: DatasetStore):
    # shortcut: explicit imports retain absent rows; reconcile removals before wiring live refresh.
    if store.source != 'nessie' or Path(filename).resolve() == store.filename.resolve():
        raise ValueError('Nessie cache and destination must be separate.')
    db = sqlite3.connect(Path(filename).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN')
        sync = db.execute('SELECT max(synced_at),sum(error IS NOT NULL) FROM workspace_sync').fetchone()

        def records():
            for row in db.execute('SELECT * FROM workspace_movements ORDER BY owner,id'):
                yield nessie_record(row)

        count = store.upsert_transactions(records())
        return {'dataset_id': 'nessie-cache-v1', 'transactions': count, 'source_mode': 'cached',
                'last_source_sync': sync[0], 'cached_sync_errors': sync[1] or 0}
    finally:
        db.close()


def nessie_record(row):
    """Normalize the typed cache projection without inheriting product display defaults."""
    day_only = bool(row['date_only'])
    return TransactionRecord(
        id=row['id'], owner=row['owner'], source='nessie',
        dataset_id='nessie-cache-v1', source_record_key=row['id'],
        account_token=row['account_token'], amount_minor=row['amount_cents'],
        currency='USD', kind=row['kind'], direction=row['direction'],
        occurred_date=date.fromisoformat(row['occurred_at'][:10]) if day_only else None,
        occurred_at=None if day_only else datetime.fromisoformat(row['occurred_at']),
        settlement_status=row['settlement_status'])
