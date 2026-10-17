from app.adapters.synthetic import load_transactions


def test_fixture_has_unique_synthetic_transactions():
    rows = load_transactions()
    assert len(rows) == 8
    assert len({row.id for row in rows}) == 8
    assert all(row.source == "synthetic" for row in rows)
