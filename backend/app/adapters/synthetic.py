import json
from pathlib import Path

from app.schemas.transaction import Transaction

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "synthetic-transactions.json"


def load_transactions() -> list[Transaction]:
    return [Transaction.model_validate(item) for item in json.loads(FIXTURE.read_text())]
