"""Isolated browser TEST FIXTURES. Never imports live transactions or provider state."""

import os
from datetime import datetime, timezone

import httpx
import uvicorn

from app.api.dependencies import get_transaction_provider
from app.core.config import Settings
from app.core.transactions import SyntheticTransactionProvider
from app.main import create_app
from app.schemas.transaction import Transaction
from tests.integration.test_fraud_memory_lifecycle import TestMemoryHTTP

if os.environ.get("APP_ENV") != "test":
    raise RuntimeError("Lifecycle fixture server requires explicit test environment")
settings = Settings(
    _env_file=None,
    app_env="test",
    transaction_provider="synthetic",
    demo_user_id="browser-fixture-owner",
    require_login=True,
    demo_user_passcode=os.environ["LIFECYCLE_PASSCODE"],
    backboard_api_key="isolated-fake-key",
    gemini_api_key="",
    nessie_api_key="",
    jev_api_key="",
    allow_memory_write=True,
)
app = create_app(settings)
rows = [
    Transaction(
        id=f"txn_fixture_{i}",
        account_token="acct_fixture",
        occurred_at=datetime(2026, 10, 17, i, tzinfo=timezone.utc),
        amount=amount,
        currency="USD",
        direction="debit",
        merchant_display=f"TEST FIXTURE {i}",
        merchant_category="groceries",
        source="synthetic",
        is_subscription=False,
        kind="purchase",
    )
    for i, amount in [(1, 300), (2, 350)]
]
provider = SyntheticTransactionProvider(rows, settings.demo_user_id)
app.dependency_overrides[get_transaction_provider] = lambda: provider
# Workspace refresh uses the same canonical fixture rows; no final responses/alerts are mocked.
with app.state.store.connect() as db:
    for tx in rows:
        db.execute(
            "INSERT OR REPLACE INTO demo_transactions "
            "(owner,id,occurred_at,amount_cents,currency,direction,merchant_display,merchant_category,"
            "source,account_token,is_subscription,kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                settings.demo_user_id,
                tx.id,
                tx.occurred_at.isoformat(),
                round(tx.amount * 100),
                tx.currency,
                tx.direction,
                tx.merchant_display,
                tx.merchant_category,
                tx.source,
                tx.account_token,
                0,
                tx.kind,
            ),
        )
# Replace only this freshly seeded isolated test owner's dataset with the two explicit fixtures.
with app.state.store.connect() as db:
    db.execute(
        "DELETE FROM demo_transactions WHERE owner=? AND id NOT LIKE 'txn_fixture_%'",
        (settings.demo_user_id,),
    )
app.state.backboard_transport = httpx.MockTransport(TestMemoryHTTP())
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ["LIFECYCLE_PORT"]),
        log_level="warning",
        access_log=False,
    )
