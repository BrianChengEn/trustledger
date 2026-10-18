"""Consistent SQLite backups, including source stores; never restores over live data."""
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

os.umask(0o077)
root = Path('/var/lib/trustledger')
backup = root / 'backups' / datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
for source in root.rglob('*.db'):
    if 'backups' in source.relative_to(root).parts:
        continue
    target = backup / source.relative_to(root)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True) as src,
          sqlite3.connect(target) as dst):
        src.backup(dst)
