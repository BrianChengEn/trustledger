"""Check a local BankSim file without copying it into the repository.

This script does not download data and does not read Kaggle credentials.
Official source and license notes live in data/manifests/banksim.yaml.

From the repository root, after the CSV is already on this machine:

    backend/.venv/bin/python scripts/prepare_research_data.py --csv /tmp/tl-eval-data/banks.csv

A path inside the repository is refused. The application database is not opened.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SHA256 = "e37006f76d993bfaec3a02d717b4f0bdc1ebfa5d36449e91fb7c07e225278377"
EXPECTED_ROWS = 594643
EXPECTED_HEADER = [
    "step", "customer", "age", "gender", "zipcodeOri", "merchant",
    "zipMerchant", "category", "amount", "fraud",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a local BankSim CSV. Do not commit it.")
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args(argv)
    path = args.csv.expanduser().resolve()
    if inside_repo(path):
        print(f"Refusing a path inside the repository: {path}", file=sys.stderr)
        return 2
    if not path.is_file():
        print("Local BankSim file was not found.", file=sys.stderr)
        print("Download bs140513_032310.csv from https://www.kaggle.com/datasets/ealaxi/banksim1", file=sys.stderr)
        print("Kaggle authentication stays in the Kaggle CLI config outside this repository.", file=sys.stderr)
        print("Do not commit ~/.kaggle/kaggle.json or any API key.", file=sys.stderr)
        return 1
    digest = sha256(path)
    with path.open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle))
        rows = sum(1 for _ in handle)
    print(f"path {path}")
    print(f"bytes {path.stat().st_size}")
    print(f"sha256 {digest}")
    print(f"rows {rows}")
    print(f"header {'ok' if header == EXPECTED_HEADER else 'mismatch'}")
    if digest != EXPECTED_SHA256 or rows != EXPECTED_ROWS or header != EXPECTED_HEADER:
        print("This file does not match the verified local BankSim checksum.", file=sys.stderr)
        return 1
    print("checksum ok")
    print("Leave this file outside git. evaluation/**/*.csv is ignored, and the raw file is not a fixture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
