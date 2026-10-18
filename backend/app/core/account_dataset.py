"""Local generated account histories using the canonical source store."""
from app.core.dataset_store import DatasetStore


class AccountDataset(DatasetStore):
    def __init__(self, filename, source):
        super().__init__(filename, source)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS accounts (
                    account_token TEXT PRIMARY KEY, owner TEXT NOT NULL UNIQUE, label TEXT NOT NULL,
                    source_owner TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS account_origins (
                    owner TEXT NOT NULL, transaction_id TEXT NOT NULL,
                    source_dataset_id TEXT NOT NULL, source_record_key TEXT NOT NULL,
                    source_owner TEXT NOT NULL, PRIMARY KEY(owner,transaction_id),
                    FOREIGN KEY(owner,transaction_id) REFERENCES transactions(owner,id));
            ''')

    def accounts(self, *, limit=25, offset=0, q=''):
        with self.connect() as db:
            where = ' WHERE instr(lower(label),lower(?))>0 OR instr(account_token,?)>0'
            args = (q, q)
            total = db.execute('SELECT count(*) FROM accounts' + where, args).fetchone()[0]
            rows = db.execute('SELECT account_token,label,(SELECT count(*) FROM transactions t '
                              'WHERE t.owner=a.owner) AS transaction_count FROM accounts a' + where +
                              ' ORDER BY label LIMIT ? OFFSET ?', (*args, limit, offset)).fetchall()
            return [dict(row) for row in rows], total

    def account_page(self, code, *, limit=25, offset=0):
        with self.connect() as db:
            account = db.execute('SELECT owner FROM accounts WHERE account_token=?', (code,)).fetchone()
            if account is None:
                return None
            total = db.execute('SELECT count(*) FROM transactions WHERE owner=?', (account['owner'],)).fetchone()[0]
        return self.list_transactions(account['owner'], limit=limit, offset=offset), total
