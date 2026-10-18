"""Pack/install versioned synthetic account snapshots; never overwrite an existing batch."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.adapters.account_demo import VERSION, digest  # noqa: E402
from app.core.account_dataset import AccountDataset  # noqa: E402

SOURCES = ('banksim', 'nessie')
DATA_FILES = ('banksim.db', 'nessie.db', 'manifest.json')
MEMBERS = {*(f'account-demo/{name}' for name in DATA_FILES),
           'DATASET-INFO.json', 'LICENSE-BANKSIM.txt'}
FORMAT = 'trustledger-account-bundle-v1'
MAX_DATABASE_BYTES = 2 * 1024**3 - 1
LICENSE = '''BankSim-derived synthetic account demonstration data
Authors: Edgar Alonso Lopez-Rojas and Stefan Axelsson (BankSim, EMSS 2014).
Source: https://www.kaggle.com/datasets/ealaxi/banksim1
Alternate source: https://www.kaggle.com/datasets/ntnu-testimon/banksim1
License: CC BY-NC-SA 4.0
https://creativecommons.org/licenses/by-nc-sa/4.0/
Changes by TrustLedger: sampled and allocated into synthetic 100-record accounts,
tokenized local identifiers, normalized exact minor-unit EUR amounts and simulated days.
The BankSim-derived data in this bundle is distributed under the same license.
Noncommercial use only; preserve attribution and share-alike terms.
Nessie-derived rows are synthetic sandbox examples, not real banking records.
No fraud labels, raw source CSV, product confirmations, or memories are included.
'''


def read_json(path):
    if path.stat().st_size > 65536:
        raise ValueError('Metadata exceeds 64 KiB.')
    return json.loads(path.read_text())


def schema(db):
    return {tuple(row) for row in db.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL")}


def validate(directory):
    manifest = read_json(directory / 'manifest.json')
    if manifest['inputs']['version'] != VERSION:
        raise ValueError('Unsupported account generator version.')
    signature = hashlib.sha256(json.dumps(manifest['inputs'], sort_keys=True).encode()).hexdigest()
    for source in SOURCES:
        path = directory / f'{source}.db'
        if path.is_symlink() or any(Path(str(path) + suffix).exists()
                                    for suffix in ('-wal', '-shm', '-journal')):
            raise ValueError('Use closed standalone source databases, without SQLite sidecars.')
        if digest(path) != manifest['database_digests'][source]:
            raise ValueError('Database checksum does not match the generation manifest.')
        with tempfile.TemporaryDirectory() as reference:
            expected = AccountDataset(Path(reference) / 'schema.db', source)
            with expected.connect() as db:
                expected_schema = schema(db)
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA trusted_schema=OFF')
            if schema(db) != expected_schema:
                raise ValueError('Only the canonical generated account schema may be shared.')
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('SQLite integrity or foreign key validation failed.')
            if db.execute('SELECT source FROM source_metadata').fetchall() != [(source,)]:
                raise ValueError('Database source mismatch.')
            for table in ('analysis_runs', 'predictions', 'human_reviews', 'source_snapshots',
                          'source_members', 'source_collections'):
                if db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone():
                    raise ValueError('Review, prediction, and runtime cache state must not be shared.')
            accounts = db.execute('SELECT account_token,owner FROM accounts').fetchall()
            report = manifest['report'][source]
            if not accounts or len(accounts) != report['accounts']:
                raise ValueError('Account count does not match the manifest.')
            if any(not re.fullmatch(r'acct_[0-9a-f]{32}', code)
                   or owner != f'{VERSION}:{source}:{code}' for code, owner in accounts):
                raise ValueError('Only generated local account identities may be shared.')
            counts = db.execute('SELECT a.owner,count(t.id) FROM accounts a LEFT JOIN transactions t '
                                'ON t.owner=a.owner GROUP BY a.owner').fetchall()
            total = db.execute('SELECT count(*) FROM transactions').fetchone()[0]
            if (any(count != 100 for _, count in counts) or total != 100 * len(accounts)
                    or total != report['transactions']
                    or db.execute('SELECT count(*) FROM account_origins').fetchone()[0] != total
                    or db.execute('SELECT 1 FROM transactions t JOIN accounts a ON a.owner=t.owner '
                                  'WHERE t.source<>? OR t.account_token<>a.account_token OR '
                                  't.dataset_id<>? LIMIT 1', (source, VERSION + ':' + signature)).fetchone()):
                raise ValueError('Account history or provenance is incomplete.')
    return manifest


def pack(source_dir, output, code_ref):
    if not re.fullmatch(r'[0-9a-f]{40}', code_ref):
        raise ValueError('Supply the full compatible code commit SHA.')
    source_dir, output = Path(source_dir).resolve(), Path(output).absolute()
    checksum_path = Path(str(output) + '.sha256')
    if os.path.lexists(output) or os.path.lexists(checksum_path):
        raise ValueError('Archive or checksum already exists; choose a new output name.')
    manifest = validate(source_dir)
    original_digests = dict(manifest['database_digests'])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.account-bundle-', dir=output.parent) as temp:
        stage = Path(temp)
        data = stage / 'account-demo'
        data.mkdir(mode=0o700)
        # Copy exact manifest-addressed bytes; a SQLite backup could include newer WAL writes.
        for source in SOURCES:
            shutil.copyfile(source_dir / f'{source}.db', data / f'{source}.db')
        (data / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        validate(data)
        for source in SOURCES:
            target = data / f'{source}.db'
            with closing(sqlite3.connect(target)) as snapshot:
                if source == 'nessie':
                    snapshot.create_function('opaque_owner', 1, lambda value:
                                             'synthetic-source:' + hashlib.sha256(value.encode()).hexdigest())
                    snapshot.execute('UPDATE accounts SET source_owner=opaque_owner(source_owner)')
                    snapshot.execute('UPDATE account_origins SET source_owner=opaque_owner(source_owner)')
                    snapshot.commit()
                # Remove free pages so deleted data cannot hitchhike in the SQLite file.
                snapshot.execute('VACUUM')
            manifest['database_digests'][source] = digest(target)
        (data / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        validate(data)
        if any(digest(source_dir / f'{s}.db') != original_digests[s] for s in SOURCES):
            raise ValueError('Source changed during packaging; no archive was published.')
        info = {'format': FORMAT, 'compatible_code_commit': code_ref,
                'generator_version': VERSION, 'inputs': manifest['inputs'],
                'report': manifest['report'], 'original_database_digests': original_digests,
                'database_digests': manifest['database_digests'],
                'transformation': 'SQLite VACUUM; Nessie provenance owners replaced with opaque local bindings.',
                'ai_assistance': 'OpenAI Codex'}
        (stage / 'DATASET-INFO.json').write_text(json.dumps(info, indent=2) + '\n')
        (stage / 'LICENSE-BANKSIM.txt').write_text(LICENSE)
        archive = stage / 'bundle.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            for member in sorted(MEMBERS):
                bundle.write(stage / member, member)
        checksum = digest(archive)
        sidecar = stage / 'checksum'
        sidecar.write_text(f'{checksum}  {output.name}\n')
        os.link(archive, output)
        try:
            os.link(sidecar, checksum_path)
        except OSError:
            output.unlink()
            raise
    return {'archive': str(output), 'sha256': checksum, 'report': manifest['report']}


def install(archive, sha256, output_dir):
    archive, output_dir = Path(archive), Path(output_dir).absolute()
    if not re.fullmatch(r'[0-9a-f]{64}', sha256) or digest(archive) != sha256:
        raise ValueError('Archive checksum mismatch; use the trusted release SHA-256.')
    if os.path.lexists(output_dir):
        raise ValueError('Destination already exists; choose a fresh output directory.')
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.account-install-', dir=output_dir.parent) as temp:
        stage = Path(temp)
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) != len(MEMBERS) or {entry.filename for entry in entries} != MEMBERS:
                raise ValueError('Unexpected or duplicate archive members.')
            for entry in entries:
                mode = entry.external_attr >> 16
                limit = MAX_DATABASE_BYTES if entry.filename.endswith('.db') else 65536
                if (entry.is_dir() or not stat.S_ISREG(mode) or entry.flag_bits & 1
                        or not 0 < entry.file_size <= limit):
                    raise ValueError('Unsupported member type or size.')
                target = stage / entry.filename
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with bundle.open(entry) as source, target.open('xb') as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
        info = read_json(stage / 'DATASET-INFO.json')
        if (info['format'] != FORMAT or not re.fullmatch(r'[0-9a-f]{40}', info['compatible_code_commit'])
                or (stage / 'LICENSE-BANKSIM.txt').read_text() != LICENSE):
            raise ValueError('Unsupported bundle metadata or missing attribution.')
        manifest = validate(stage / 'account-demo')
        if any(info[key] != manifest[key] for key in ('inputs', 'report', 'database_digests')):
            raise ValueError('Bundle metadata does not match the dataset.')
        # Retain release provenance alongside the installed runtime batch.
        for name in ('DATASET-INFO.json', 'LICENSE-BANKSIM.txt'):
            shutil.move(stage / name, stage / 'account-demo' / name)
        output_dir.mkdir(mode=0o700)
        published = []
        try:
            # Existing readers discover only manifest.json; publish that readiness marker last.
            for name in ('banksim.db', 'nessie.db', 'DATASET-INFO.json',
                         'LICENSE-BANKSIM.txt', 'manifest.json'):
                original, target = stage / 'account-demo' / name, output_dir / name
                os.link(original, target)
                published.append((original, target))
        except OSError:
            for original, target in reversed(published):
                if target.exists() and os.path.samestat(original.stat(), target.stat()):
                    target.unlink()
            try:
                output_dir.rmdir()
            except OSError:
                pass  # Preserve files created by another process in the reserved directory.
            raise
        # shortcut: a crash before the manifest may leave an unpublished directory; use a fresh path.
    return {'installed': str(output_dir), 'compatible_code_commit': info['compatible_code_commit'],
            'report': manifest['report']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('pack', help='Create a label-free, compact synthetic release archive.')
    create.add_argument('--source-dir', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    create.add_argument('--code-ref', required=True)
    receive = commands.add_parser('install', help='Verify and install into an absent account-demo directory.')
    receive.add_argument('--archive', type=Path, required=True)
    receive.add_argument('--sha256', required=True)
    receive.add_argument('--output-dir', type=Path, default=ROOT / 'backend/data/sources/account-demo')
    args = vars(parser.parse_args())
    command = args.pop('command')
    try:
        print(json.dumps((pack if command == 'pack' else install)(**args), indent=2))
    except ValueError as error:
        parser.exit(1, f'Bundle validation failed: {error}\n')
    except (KeyError, TypeError, OSError, sqlite3.Error, zipfile.BadZipFile):
        parser.exit(1, 'Bundle validation failed. Check the source manifest, archive checksum, '
                    'compatible format, and use a fresh destination. Existing data was not replaced.\n')


if __name__ == '__main__':
    main()
