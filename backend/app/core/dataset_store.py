"""Source-bound SQLite storage. Ground truth is deliberately absent."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.schemas.dataset import AnalysisRun, BankSimFeatures, HumanReview, Prediction, TransactionRecord

COLUMNS = tuple(name for name in TransactionRecord.model_fields if name != 'banksim_features')
FEATURE_COLUMNS = tuple(BankSimFeatures.model_fields)

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_metadata (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    source TEXT NOT NULL UNIQUE CHECK(source IN ('nessie','banksim')));
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT NOT NULL, owner TEXT NOT NULL,
    source TEXT NOT NULL REFERENCES source_metadata(source),
    dataset_id TEXT NOT NULL, source_record_key TEXT NOT NULL,
    customer_token TEXT, account_token TEXT,
    amount_minor INTEGER NOT NULL CHECK(typeof(amount_minor)='integer' AND amount_minor>=0
        AND amount_minor<=9007199254740991),
    currency TEXT, kind TEXT NOT NULL CHECK(kind IN
        ('purchase','transfer','deposit','withdrawal','unknown')),
    direction TEXT NOT NULL CHECK(direction IN ('debit','credit','unknown')),
    merchant_token TEXT, merchant_display TEXT, merchant_category TEXT, source_category TEXT,
    occurred_at TEXT, occurred_date TEXT,
    simulation_step INTEGER CHECK(simulation_step IS NULL OR
        (typeof(simulation_step)='integer' AND simulation_step>=0)),
    is_subscription INTEGER CHECK(is_subscription IN (0,1)),
    settlement_status TEXT CHECK(settlement_status IN ('pending','completed','cancelled')),
    PRIMARY KEY(owner,id), UNIQUE(owner,dataset_id,source_record_key),
    CHECK((occurred_at IS NOT NULL)+(occurred_date IS NOT NULL)+
        (simulation_step IS NOT NULL)<=1),
    CHECK((source='banksim' AND simulation_step IS NOT NULL) OR
        (source='nessie' AND simulation_step IS NULL)));
CREATE INDEX IF NOT EXISTS transactions_step ON transactions(owner,simulation_step,source_record_key,id);
CREATE INDEX IF NOT EXISTS transactions_date ON transactions(owner,occurred_date,occurred_at,id);
CREATE TABLE IF NOT EXISTS banksim_features (
    owner TEXT NOT NULL, transaction_id TEXT NOT NULL,
    customer_code TEXT NOT NULL, merchant_code TEXT NOT NULL,
    age_band TEXT, gender TEXT, zipcode_origin TEXT, zipcode_merchant TEXT,
    PRIMARY KEY(owner,transaction_id), FOREIGN KEY(owner,transaction_id)
        REFERENCES transactions(owner,id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL,
    provider TEXT NOT NULL CHECK(provider IN ('rules-only','jev','rules+jev','research-model')),
    model_version TEXT, positive_mapping TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS predictions (
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id), owner TEXT NOT NULL,
    transaction_id TEXT NOT NULL, predicted_positive INTEGER CHECK(predicted_positive IN (0,1)),
    score REAL CHECK(score>=0 AND score<=1),
    status TEXT NOT NULL CHECK(status IN ('success','degraded','failed')),
    PRIMARY KEY(run_id,owner,transaction_id), FOREIGN KEY(owner,transaction_id)
        REFERENCES transactions(owner,id),
    CHECK((status='success' AND predicted_positive IS NOT NULL) OR
        (status<>'success' AND predicted_positive IS NULL AND score IS NULL)));
CREATE TABLE IF NOT EXISTS human_reviews (
    owner TEXT NOT NULL, transaction_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('normal','review')),
    consent INTEGER NOT NULL CHECK(consent IN (0,1)), reviewed_at TEXT NOT NULL,
    PRIMARY KEY(owner,transaction_id), FOREIGN KEY(owner,transaction_id)
        REFERENCES transactions(owner,id));
"""


class DatasetStore:
    def __init__(self, filename: Path, source: str):
        if source not in {'nessie', 'banksim'}:
            raise ValueError('Unsupported source.')
        self.filename, self.source = Path(filename), source
        self.filename.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and 'source_metadata' not in tables:
                raise ValueError('Refusing an existing non-source database.')
            if 'source_metadata' in tables:
                stored = db.execute('SELECT source FROM source_metadata WHERE singleton=1').fetchone()
                if stored is None or stored['source'] != source:
                    raise ValueError('Database source does not match.')
            db.executescript(SCHEMA)
            db.execute('INSERT OR IGNORE INTO source_metadata VALUES(1,?)', (source,))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.filename, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def upsert_transactions(self, records):
        count = 0
        with self.connect() as db:
            for value in records:
                row = TransactionRecord.model_validate(value.model_dump())
                if row.source != self.source:
                    raise ValueError('Transaction source does not match database source.')
                existing = db.execute('SELECT dataset_id,source_record_key FROM transactions '
                                      'WHERE owner=? AND id=?', (row.owner, row.id)).fetchone()
                if existing and tuple(existing) != (row.dataset_id, row.source_record_key):
                    raise ValueError('Transaction identity cannot change.')
                payload = row.model_dump(mode='json', exclude={'banksim_features'})
                db.execute('INSERT INTO transactions (' + ','.join(COLUMNS) + ') VALUES (' +
                           ','.join('?' for _ in COLUMNS) + ') ON CONFLICT(owner,id) DO UPDATE SET ' +
                           ','.join(f'{name}=excluded.{name}' for name in COLUMNS if name not in {'owner', 'id'}),
                           tuple(payload[name] for name in COLUMNS))
                if row.banksim_features is not None:
                    values = row.banksim_features.model_dump()
                    db.execute('INSERT INTO banksim_features VALUES(?,?,?,?,?,?,?,?) '
                               'ON CONFLICT(owner,transaction_id) DO UPDATE SET ' +
                               ','.join(f'{name}=excluded.{name}' for name in FEATURE_COLUMNS),
                               (row.owner, row.id, *(values[name] for name in FEATURE_COLUMNS)))
                else:
                    db.execute('DELETE FROM banksim_features WHERE owner=? AND transaction_id=?',
                               (row.owner, row.id))
                count += 1
        return count

    def list_transactions(self, owner, *, limit=100, offset=0):
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise ValueError('Invalid page.')
        with self.connect() as db:
            rows = db.execute('SELECT * FROM transactions WHERE owner=? '
                              'ORDER BY simulation_step,occurred_date,occurred_at,source_record_key,id '
                              'LIMIT ? OFFSET ?',
                              (owner, limit, offset)).fetchall()
            result = []
            for stored in rows:
                payload = dict(stored)
                if payload['is_subscription'] is not None:
                    payload['is_subscription'] = bool(payload['is_subscription'])
                features = db.execute('SELECT ' + ','.join(FEATURE_COLUMNS) +
                                      ' FROM banksim_features WHERE owner=? AND transaction_id=?',
                                      (owner, stored['id'])).fetchone()
                payload['banksim_features'] = dict(features) if features else None
                result.append(TransactionRecord.model_validate(payload))
        return result

    def create_analysis_run(self, run_id, dataset_id, provider, model_version, positive_mapping, created_at):
        row = AnalysisRun(run_id=run_id, dataset_id=dataset_id, provider=provider,
                          model_version=model_version, positive_mapping=positive_mapping,
                          created_at=created_at)
        with self.connect() as db:
            db.execute('INSERT INTO analysis_runs VALUES(?,?,?,?,?,?)',
                       tuple(row.model_dump(mode='json').values()))

    def save_prediction(self, run_id, owner, transaction_id, *, predicted_positive, score=None,
                        status='success'):
        row = Prediction(run_id=run_id, owner=owner, transaction_id=transaction_id,
                         predicted_positive=predicted_positive, score=score, status=status)
        with self.connect() as db:
            datasets = db.execute('SELECT t.dataset_id,r.dataset_id FROM transactions t '
                                  'JOIN analysis_runs r ON r.run_id=? '
                                  'WHERE t.owner=? AND t.id=?', (run_id, owner, transaction_id)).fetchone()
            if datasets and datasets[0] != datasets[1]:
                raise ValueError('Prediction dataset does not match transaction dataset.')
            db.execute('INSERT INTO predictions VALUES(?,?,?,?,?,?)', tuple(row.model_dump().values()))

    def list_predictions(self, run_id, owner, *, limit=100, offset=0):
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise ValueError('Invalid page.')
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM predictions WHERE run_id=? AND owner=? '
                'ORDER BY transaction_id LIMIT ? OFFSET ?', (run_id, owner, limit, offset))]

    def save_review(self, owner, transaction_id, decision, consent, reviewed_at):
        row = HumanReview(owner=owner, transaction_id=transaction_id, decision=decision,
                          consent=consent, reviewed_at=reviewed_at)
        with self.connect() as db:
            db.execute('INSERT INTO human_reviews VALUES(?,?,?,?,?) ON CONFLICT(owner,transaction_id) '
                       'DO UPDATE SET decision=excluded.decision,consent=excluded.consent,'
                       'reviewed_at=excluded.reviewed_at', tuple(row.model_dump(mode='json').values()))
