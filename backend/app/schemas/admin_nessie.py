from typing import Any, Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.adapters.nessie import QUERIES, REMOTE_ID
from app.schemas.api import StrictModel


class QueryRequest(StrictModel):
    query: Literal["customers.list", "accounts.list", "accounts.get", "accounts.by_customer",
                   "deposits.by_account", "withdrawals.by_account"]
    resource_id: str | None = Field(default=None, max_length=128,
                                   description="Trimmed, lowercase 24-hex ID or canonical UUID; "
                                               "required for resource queries, absent for lists.")

    @model_validator(mode="after")
    def validate_id(self):
        self.resource_id = (self.resource_id or "").strip().lower() or None
        if "{id}" in QUERIES[self.query]:
            if not self.resource_id or not REMOTE_ID.fullmatch(self.resource_id):
                raise ValueError("A 24-character hexadecimal ID or canonical UUID is required")
        elif self.resource_id:
            raise ValueError("This query does not accept an ID")
        return self


class CompareRequest(StrictModel):
    left_id: StrictInt = Field(gt=0)
    right_id: StrictInt = Field(gt=0)

    @model_validator(mode="after")
    def distinct(self):
        if self.left_id == self.right_id:
            raise ValueError("Select distinct history records")
        return self


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
    resource_id: str | None
    requested_at: str
    duration_ms: int = Field(ge=0)
    http_status: int | None = Field(ge=100, le=599)
    body_format: Literal["json", "text", "none"]
    transport_error: TransportError | None


class Execution(HistoryItem):
    history_id: int | None = Field(gt=0)
    response_body: Any
    write_status: Literal["saved", "failed"]
    write_label: Literal["failed to write"] | None


class HistoryPage(StrictModel):
    items: list[HistoryItem]
    next_cursor: int | None


class SnapshotChange(StrictModel):
    kind: Literal["added", "removed", "changed"]
    record_id: str | None = None
    path: str
    before_present: bool
    after_present: bool
    before: Any
    after: Any


class StatusChange(StrictModel):
    before: int | None
    after: int | None


class TransportChange(StrictModel):
    before: TransportError | None
    after: TransportError | None


class ComparisonData(StrictModel):
    data_changed: bool
    changes: list[SnapshotChange]
    status_change: StatusChange | None
    transport_change: TransportChange | None


class Comparison(StrictModel):
    left: Execution
    right: Execution
    comparison: ComparisonData


class DeleteOutcome(StrictModel):
    deleted: int = Field(ge=0)
