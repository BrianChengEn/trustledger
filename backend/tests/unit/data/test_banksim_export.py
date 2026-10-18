import csv
import importlib
from pathlib import Path

import pytest

from app.adapters.dataset_import import HEADER, import_banksim
from app.core.dataset_store import DatasetStore


def exporter(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4]))
    return importlib.import_module('evaluation.banksim_database').export_database


def test_research_export_restores_every_row_and_original_order(tmp_path, monkeypatch):
    source = tmp_path / 'banks.csv'
    rows = [[179 - index, f'C{index}', '2', 'F', '28007', 'M123', '28007',
             'es_health', '180.01', str(index % 2)] for index in range(103)]
    with source.open('w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)
        writer.writerows(rows)
    store = DatasetStore(tmp_path / 'banksim.db', 'banksim')
    import_banksim(source, store)
    before = store.filename.read_bytes()
    output = tmp_path / 'research.csv'
    report = exporter(monkeypatch)(store.filename, source, output)
    with output.open(newline='') as file:
        restored = list(csv.reader(file))
    assert restored == [HEADER] + [[str(value) for value in row] for row in rows]
    assert report['transactions'] == 103 and report['fraud_labels'] == 51
    assert report['splits']['test'] == {'rows': 30, 'fraud': 15}
    assert report['currency'] == 'EUR' and report['simulation_step_unit'] == 'day'
    assert store.filename.read_bytes() == before


@pytest.mark.parametrize('corruption', [
    "UPDATE banksim_features SET merchant_code='wrong' WHERE transaction_id=(SELECT max(id) FROM transactions)",
    "UPDATE transactions SET amount_minor=amount_minor+1 WHERE source_record_key='000000000002'",
    "UPDATE transactions SET currency='USD' WHERE source_record_key='000000000002'",
    "DELETE FROM banksim_features WHERE transaction_id=(SELECT max(id) FROM transactions)",
    "DELETE FROM transactions WHERE source_record_key='000000000002'",
])
def test_corrupt_database_never_publishes_partial_research_data(tmp_path, monkeypatch, corruption):
    source = tmp_path / 'banks.csv'
    with source.open('w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)
        writer.writerows([[120, 'C1', '2', 'F', '28007', 'M1', '28007', 'es_health', '180.01', 1]] * 2)
    store = DatasetStore(tmp_path / 'banksim.db', 'banksim')
    import_banksim(source, store)
    with store.connect() as db:
        # Delete the dependent feature first when exercising a missing transaction.
        if corruption.startswith('DELETE FROM transactions'):
            db.execute("DELETE FROM banksim_features WHERE transaction_id=(SELECT id FROM transactions WHERE source_record_key='000000000002')")
        db.execute(corruption)
    files = set(tmp_path.iterdir())
    with pytest.raises(ValueError, match='mismatch|differ'):
        exporter(monkeypatch)(store.filename, source, tmp_path / 'research.csv')
    assert set(tmp_path.iterdir()) == files


def test_export_refuses_git_destination_and_keeps_existing_artifacts(tmp_path, monkeypatch):
    source = tmp_path / 'banks.csv'
    with source.open('w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)
        writer.writerow([0, 'C1', '2', 'F', '28007', 'M1', '28007', 'es_health', '0.01', 0])
    store = DatasetStore(tmp_path / 'banksim.db', 'banksim')
    import_banksim(source, store)
    export = exporter(monkeypatch)
    output = tmp_path / 'existing.csv'
    output.write_text('previous research')
    with pytest.raises(FileExistsError):
        export(store.filename, source, output)
    assert output.read_text() == 'previous research'
    (tmp_path / '.git').touch()
    with pytest.raises(ValueError, match='outside git'):
        export(store.filename, source, tmp_path / 'new.csv')
    assert not (tmp_path / 'new.csv').exists()
