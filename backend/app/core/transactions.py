"""Backend boundary for canonical transactions, not a Nessie wire schema.

Provider owners must tokenize identifiers before returning canonical DTOs. There is
no live selection or automatic fallback: an injected provider remains authoritative.
The current list/get interface has no pagination; rule context uses the latest 100
records. Larger history windows require coordination with the Data/AI owners.
"""
from dataclasses import dataclass
from math import isfinite
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from app.schemas.transaction import Transaction


@dataclass(frozen=True)
class UserContext:
    user_id: str


class AdapterHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "degraded"]
    data_mode: Literal["synthetic", "nessie-live", "degraded"]


class ProviderError(Exception):
    """Internal categories only; exception text must never reach logs or clients."""


class ProviderUnavailable(ProviderError):
    pass


class ProviderTimeout(ProviderError):
    pass


class ProviderMalformedData(ProviderError):
    pass


class TransactionNotFound(ProviderError):
    pass


class TransactionProvider(Protocol):
    def list_transactions(self, user_context: UserContext, limit: int = 25) -> list[Transaction]: ...

    def get_transaction(self, user_context: UserContext, transaction_id: str) -> Transaction | None: ...

    def health(self) -> AdapterHealth: ...


class SyntheticTransactionProvider:
    """Wrap the existing fixture output without changing Data-owned code."""

    def __init__(self, transactions: list[Transaction], owner_id: str):
        self.transactions = transactions
        self.owner_id = owner_id

    def list_transactions(self, user_context: UserContext, limit: int = 25) -> list[Transaction]:
        if user_context.user_id != self.owner_id:
            return []
        return sorted(self.transactions, key=lambda tx: tx.occurred_at, reverse=True)[:limit]

    def get_transaction(self, user_context: UserContext, transaction_id: str) -> Transaction | None:
        if user_context.user_id != self.owner_id:
            return None
        return next((tx for tx in self.transactions if tx.id == transaction_id), None)

    def health(self) -> AdapterHealth:
        return AdapterHealth(status="ok", data_mode="synthetic")


class SQLiteTransactionProvider:
    """Read the initialized synthetic SQLite dataset without caching or fallback."""

    def __init__(self, store, owner_id: str):
        self.store = store
        self.owner_id = owner_id

    def list_transactions(self, user_context: UserContext, limit: int = 25) -> list[Transaction]:
        if user_context.user_id != self.owner_id:
            return []
        rows = provider_call(self.store.list_transactions, self.owner_id)
        return sorted([canonical(row) for row in rows], key=lambda tx: tx.occurred_at, reverse=True)[:limit]

    def get_transaction(self, user_context: UserContext, transaction_id: str) -> Transaction | None:
        if user_context.user_id != self.owner_id:
            return None
        rows = provider_call(self.store.list_transactions, self.owner_id)
        return next((canonical(row) for row in rows if row.id == transaction_id), None)

    def health(self) -> AdapterHealth:
        try:
            self.list_transactions(UserContext(self.owner_id), 1)
            return AdapterHealth(status="ok", data_mode="synthetic")
        except ProviderError:
            return AdapterHealth(status="degraded", data_mode="degraded")


def provider_call(method, *args):
    try:
        return method(*args)
    except ProviderError:
        raise
    except TimeoutError:
        raise ProviderTimeout() from None
    except ValidationError:
        raise ProviderMalformedData() from None
    except Exception:
        raise ProviderUnavailable() from None


def canonical(value) -> Transaction:
    try:
        # Revalidate even model instances: model_copy/model_construct can bypass validation.
        if isinstance(value, Transaction):
            value = value.model_dump(warnings=False)
        result = Transaction.model_validate(value)
        # JSON numbers and rule arithmetic require finite canonical amounts.
        if not isfinite(result.amount):
            raise ProviderMalformedData()
        return result
    except (ValidationError, TypeError, ValueError):
        raise ProviderMalformedData() from None


class TransactionService:
    def __init__(self, provider: TransactionProvider, user_context: UserContext):
        self.provider = provider
        self.user_context = user_context
        self._history: list[Transaction] | None = None

    def list_transactions(self, limit: int = 25) -> list[Transaction]:
        rows = provider_call(self.provider.list_transactions, self.user_context, limit)
        if not isinstance(rows, list) or len(rows) > limit:
            raise ProviderMalformedData()
        result = [canonical(row) for row in rows]
        if len({tx.id for tx in result}) != len(result):
            raise ProviderMalformedData()
        return sorted(result, key=lambda tx: tx.occurred_at, reverse=True)

    def get_transaction(self, transaction_id: str) -> Transaction:
        value = provider_call(self.provider.get_transaction, self.user_context, transaction_id)
        if value is None:
            raise TransactionNotFound()
        tx = canonical(value)
        if tx.id != transaction_id:
            raise ProviderMalformedData()
        if self._history is not None:
            listed = next((row for row in self._history if row.id == tx.id), None)
            if (listed is None and len(self._history) < 100) or (listed is not None and listed != tx):
                raise ProviderMalformedData()
        return tx

    def history(self) -> list[Transaction]:
        if self._history is None:
            self._history = self.list_transactions(100)
        return self._history

    def health(self) -> AdapterHealth:
        try:
            value = provider_call(self.provider.health)
            if isinstance(value, AdapterHealth):
                value = value.model_dump(warnings=False)
            result = AdapterHealth.model_validate(value)
            # A degraded data source must not be advertised as overall healthy.
            if result.data_mode == "degraded":
                result.status = "degraded"
            return result
        except (ProviderError, ValidationError):
            return AdapterHealth(status="degraded", data_mode="degraded")
