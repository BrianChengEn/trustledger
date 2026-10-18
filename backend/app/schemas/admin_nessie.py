from typing import Any, Literal
import re

from pydantic import Field, StrictBool, model_validator

from app.adapters.nessie import QUERIES
from app.schemas.api import StrictModel


class QueryRequest(StrictModel):
    query: Literal["customers.list", "accounts.list", "accounts.get", "accounts.by_customer",
                   "deposits.by_account", "withdrawals.by_account"]
    resource_id: str | None = Field(default=None, max_length=41,
                                   description="Server-issued local customer/account code only.")

    @model_validator(mode="after")
    def validate_id(self):
        if "{id}" in QUERIES[self.query]:
            kind = "customer" if self.query == "accounts.by_customer" else "account"
            if not re.fullmatch(kind + r"_[0-9a-f]{32}", self.resource_id or ""):
                raise ValueError("Select a server-issued local resource code")
        elif self.resource_id is not None:
            raise ValueError("This query does not accept a resource code")
        return self


class ResourceOption(StrictModel):
    resource_id: str
    kind: Literal["customer", "account"]


class DeleteRequest(StrictModel):
    confirm: StrictBool

    @model_validator(mode="after")
    def confirmed(self):
        if not self.confirm:
            raise ValueError("Deletion must be confirmed")
        return self


class TransportError(StrictModel):
    type: Literal["timeout", "connection"]
    message: str


class HistoryItem(StrictModel):
    history_id: int = Field(gt=0)
    source: Literal["nessie", "synthetic"]
    query: str
    requested_at: str
    duration_ms: int = Field(ge=0)
    http_status: int | None = Field(ge=100, le=599)
    transport_error: TransportError | None


class Execution(HistoryItem):
    history_id: int | None = Field(gt=0)
    response_body: Any
    body_format: Literal["json", "none"]
    write_status: Literal["saved", "failed"]
    write_label: Literal["failed to write"] | None


class HistoryPage(StrictModel):
    items: list[HistoryItem]
    next_cursor: int | None


class DeleteOutcome(StrictModel):
    deleted: int = Field(ge=0)
