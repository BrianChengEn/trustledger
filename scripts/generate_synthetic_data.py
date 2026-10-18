"""Generate/check offline JSON compatibility fixtures; runtime data lives in SQLite."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.adapters.synthetic_dataset import main  # noqa: E402

if __name__ == "__main__":
    main()
    import json
    from app.adapters.synthetic import load_transactions

    fixture = Path(__file__).resolve().parents[1] / 'fixtures' / 'synthetic-transactions.json'
    expected = [row.model_dump(mode='json') for row in load_transactions()]
    if '--check' in sys.argv:
        assert json.loads(fixture.read_text()) == expected, 'Canonical synthetic fixture differs from SQLite definitions'
        print('Verified 18 canonical transactions including 10 transfers.')
    else:
        fixture.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + '\n')
        print('Generated 18 canonical transactions including 10 transfers.')
