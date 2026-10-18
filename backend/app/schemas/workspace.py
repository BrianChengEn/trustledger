from datetime import datetime
from typing import Literal

from app.schemas.api import StrictModel
from app.schemas.transaction import Transaction


class WorkspaceAccount(StrictModel):
    account_token: str
    type: Literal['Checking', 'Savings', 'Credit Card']
    balance: float
    rewards: int


class WorkspaceMovement(Transaction):
    kind: Literal['purchase', 'transfer', 'deposit', 'withdrawal']
    settlement_status: Literal['pending', 'completed', 'cancelled']
    date_only: bool


class CollectionStatus(StrictModel):
    account_token: str
    kind: Literal['accounts', 'purchases', 'transfers', 'deposits', 'withdrawals']
    requested_at: datetime
    synced_at: datetime | None
    http_status: int | None
    error: Literal['upstream', 'timeout', 'connection', 'schema'] | None


class WorkspaceSnapshot(StrictModel):
    customer_id: str | None
    data_mode: Literal['synthetic', 'nessie-live', 'degraded']
    accounts: list[WorkspaceAccount]
    transactions: list[WorkspaceMovement]
    sync: list[CollectionStatus]
