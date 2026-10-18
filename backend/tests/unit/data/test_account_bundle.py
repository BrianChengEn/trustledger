import hashlib
import json
import os
from pathlib import Path
import runpy
import sqlite3
import subprocess
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.adapters.account_demo import build_account_demo
from app.core.config import Settings
from app.main import create_app
from tests.unit.data.test_account_demo import inputs

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / 'scripts/account_demo_bundle.py'
CODE_REF = '8fbf407fdcaeb6a0cc39085406f649a82936e7fb'


def cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True)


def batch(tmp_path):
    csv, nessie = inputs(tmp_path)
    target = tmp_path / 'original'
    build_account_demo(csv, nessie, target, tmp_path / 'labels')
    return target


def test_bundle_round_trip_preserves_transactions_and_excludes_private_state(tmp_path):
    source = batch(tmp_path)
    archive = tmp_path / 'dataset.zip'
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    result = cli('pack', '--source-dir', source, '--output', archive, '--code-ref', CODE_REF)
    assert result.returncode == 0, result.stderr
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert (tmp_path / 'dataset.zip.sha256').read_text().split()[0] == checksum
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {
            'account-demo/banksim.db', 'account-demo/nessie.db', 'account-demo/manifest.json',
            'DATASET-INFO.json', 'LICENSE-BANKSIM.txt'}
        assert json.loads(bundle.read('DATASET-INFO.json'))['compatible_code_commit'] == CODE_REF
    target = tmp_path / 'installed'
    result = cli('install', '--archive', archive, '--sha256', checksum, '--output-dir', target)
    assert result.returncode == 0, result.stderr
    for name in ['banksim', 'nessie']:
        with sqlite3.connect(source / f'{name}.db') as original, sqlite3.connect(target / f'{name}.db') as installed:
            assert original.execute('SELECT * FROM transactions ORDER BY owner,id').fetchall() == installed.execute('SELECT * FROM transactions ORDER BY owner,id').fetchall()
            assert installed.execute('PRAGMA integrity_check').fetchone() == ('ok',)
            assert installed.execute('PRAGMA foreign_key_check').fetchall() == []
            if name == 'nessie':
                assert all(row[0].startswith('synthetic-source:') for row in installed.execute('SELECT source_owner FROM accounts'))
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()} == before
    app = create_app(Settings(_env_file=None, database_path=tmp_path / 'product.db',
                              source_database_dir=tmp_path))
    # Install into the existing source registry, without changing the product baseline.
    target.rename(tmp_path / 'account-demo')
    with TestClient(app, base_url='http://127.0.0.1') as client:
        for source, count, currency in [('banksim', 12, 'EUR'), ('nessie', 2, 'USD')]:
            accounts = client.get(f'/api/v1/data-sources/{source}/accounts').json()
            assert accounts['total'] == count
            code = accounts['items'][0]['account_token']
            records = client.get(f'/api/v1/data-sources/{source}/transactions',
                                 params={'account_token': code, 'limit': 100}).json()
            assert records['total'] == len(records['items']) == 100
            assert records['data_mode'] == 'synthetic-derived'
            assert {row['currency'] for row in records['items']} == {currency}
        assert len(client.get('/api/v1/transactions?limit=100').json()) == 18


@pytest.fixture
def packed(tmp_path):
    source = batch(tmp_path)
    archive = tmp_path / 'dataset.zip'
    result = cli('pack', '--source-dir', source, '--output', archive, '--code-ref', CODE_REF)
    assert result.returncode == 0, result.stderr
    return source, archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def test_install_rejects_wrong_checksum_and_existing_destinations(tmp_path, packed):
    _, archive, checksum = packed
    target = tmp_path / 'existing'
    assert cli('install', '--archive', archive, '--sha256', '0' * 64,
               '--output-dir', target).returncode != 0
    assert not target.exists()
    target.mkdir()
    marker = target / 'keep.txt'
    marker.write_text('untouched')
    assert cli('install', '--archive', archive, '--sha256', checksum,
               '--output-dir', target).returncode != 0
    assert marker.read_text() == 'untouched'
    linked = tmp_path / 'symlink'
    linked.symlink_to(tmp_path / 'missing', target_is_directory=True)
    assert cli('install', '--archive', archive, '--sha256', checksum,
               '--output-dir', linked).returncode != 0
    assert linked.is_symlink() and not linked.exists()
    # A failed repeat pack also preserves the original archive and sidecar.
    assert cli('pack', '--source-dir', packed[0], '--output', archive,
               '--code-ref', CODE_REF).returncode != 0
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == checksum


@pytest.mark.parametrize('attack', ['traversal', 'symlink', 'duplicate', 'corrupt-db', 'metadata'])
def test_install_rejects_unsafe_archives_without_partial_publication(tmp_path, packed, attack):
    _, archive, _ = packed
    unsafe = tmp_path / 'unsafe.zip'
    with zipfile.ZipFile(archive) as original, zipfile.ZipFile(unsafe, 'w') as modified:
        for entry in original.infolist():
            content = original.read(entry)
            if entry.filename == 'account-demo/nessie.db':
                if attack == 'traversal':
                    entry.filename = '../escaped.db'
                elif attack == 'symlink':
                    entry.external_attr = 0o120777 << 16
                elif attack == 'corrupt-db':
                    content = b'not a database'
                elif attack == 'duplicate':
                    entry.filename = 'account-demo/banksim.db'
            if attack == 'metadata' and entry.filename == 'DATASET-INFO.json':
                info = json.loads(content)
                info['report']['nessie']['accounts'] += 1
                content = json.dumps(info).encode()
            modified.writestr(entry, content)
    target = tmp_path / 'installed'
    result = cli('install', '--archive', unsafe, '--sha256',
                 hashlib.sha256(unsafe.read_bytes()).hexdigest(), '--output-dir', target)
    assert result.returncode != 0
    assert not target.exists() and not (tmp_path / 'escaped.db').exists()
    assert not list(tmp_path.glob('.account-install-*'))


@pytest.mark.parametrize('change', ['unknown-table', 'review', 'missing-history', 'wal'])
def test_pack_rejects_private_or_incomplete_sources(tmp_path, change):
    source = batch(tmp_path)
    path = source / 'nessie.db'
    with sqlite3.connect(path) as db:
        if change == 'unknown-table':
            db.execute('CREATE TABLE private_secrets (secret TEXT)')
        elif change == 'review':
            db.execute("INSERT INTO human_reviews SELECT owner,id,'normal',1,'2026-10-18' FROM transactions LIMIT 1")
        elif change == 'missing-history':
            db.execute('DELETE FROM transactions WHERE id=(SELECT id FROM transactions LIMIT 1)')
    if change == 'wal':
        Path(str(path) + '-wal').write_bytes(b'active source')
    # Even an updated fingerprint cannot turn private state into a shareable snapshot.
    manifest = json.loads((source / 'manifest.json').read_text())
    manifest['database_digests']['nessie'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (source / 'manifest.json').write_text(json.dumps(manifest))
    archive = tmp_path / 'dataset.zip'
    assert cli('pack', '--source-dir', source, '--output', archive,
               '--code-ref', CODE_REF).returncode != 0
    assert not archive.exists() and not Path(str(archive) + '.sha256').exists()


def test_install_never_replaces_a_late_empty_destination(tmp_path, packed, monkeypatch):
    module = runpy.run_path(str(SCRIPT))
    target = tmp_path / 'late-directory'
    mkdir = Path.mkdir

    def competing_mkdir(path, *args, **kwargs):
        if path == target:
            mkdir(path)
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'mkdir', competing_mkdir)
    with pytest.raises(FileExistsError):
        module['install'](packed[1], packed[2], target)
    assert target.is_dir() and list(target.iterdir()) == []


def test_failed_publication_never_exposes_a_manifest_or_deletes_other_files(tmp_path, packed, monkeypatch):
    module = runpy.run_path(str(SCRIPT))
    target = tmp_path / 'interrupted'
    link = os.link

    def interrupted_link(source, destination):
        if destination == target / 'manifest.json':
            assert not (target / 'manifest.json').exists()
            (target / 'other-process.txt').write_text('preserve')
            raise OSError('simulated interrupted publication')
        return link(source, destination)

    monkeypatch.setattr(os, 'link', interrupted_link)
    with pytest.raises(OSError, match='interrupted publication'):
        module['install'](packed[1], packed[2], target)
    assert [p.name for p in target.iterdir()] == ['other-process.txt']
    assert (target / 'other-process.txt').read_text() == 'preserve'


def test_pack_uses_exact_manifest_bytes_even_if_a_wal_writer_appears(tmp_path, monkeypatch):
    module = runpy.run_path(str(SCRIPT))
    source = batch(tmp_path)
    path = source / 'nessie.db'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL')
    # Close/checkpoint the source so this begins as a valid standalone batch.
    manifest = json.loads((source / 'manifest.json').read_text())
    manifest['database_digests']['nessie'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (source / 'manifest.json').write_text(json.dumps(manifest))
    writer = sqlite3.connect(path)
    copy = module['shutil'].copyfile

    def concurrent_write(original, target, *args, **kwargs):
        if Path(original) == path:
            writer.execute("UPDATE transactions SET merchant_display='newer-private-wal-value'")
            writer.commit()
        return copy(original, target, *args, **kwargs)

    monkeypatch.setattr(module['shutil'], 'copyfile', concurrent_write)
    try:
        archive = tmp_path / 'dataset.zip'
        module['pack'](source, archive, CODE_REF)
        with zipfile.ZipFile(archive) as bundle:
            assert b'newer-private-wal-value' not in bundle.read('account-demo/nessie.db')
    finally:
        writer.close()


def test_pack_removes_deleted_page_content_and_private_provenance_bytes(tmp_path):
    source = batch(tmp_path)
    path = source / 'nessie.db'
    secret = 'deleted-private-review-marker-' * 200
    owner = 'credential-scoped-private-source-owner'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA secure_delete=OFF')
        db.execute('INSERT INTO human_reviews SELECT owner,id,\'normal\',1,? FROM transactions LIMIT 1', (secret,))
        db.execute('DELETE FROM human_reviews')
        db.execute('UPDATE accounts SET source_owner=?', (owner,))
        db.execute('UPDATE account_origins SET source_owner=?', (owner,))
    assert b'deleted-private-review-marker-' in path.read_bytes()
    manifest = json.loads((source / 'manifest.json').read_text())
    manifest['database_digests']['nessie'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (source / 'manifest.json').write_text(json.dumps(manifest))
    archive = tmp_path / 'dataset.zip'
    result = cli('pack', '--source-dir', source, '--output', archive, '--code-ref', CODE_REF)
    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(archive) as bundle:
        contents = bundle.read('account-demo/nessie.db')
        assert b'deleted-private-review-marker-' not in contents
        assert owner.encode() not in contents
