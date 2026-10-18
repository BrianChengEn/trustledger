import re
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.ai.privacy import CATEGORIES

ROW_CAP = 60
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class DemoModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _merchant(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 80 or _CONTROL.search(value):
        raise ValueError("Merchant must be 1 to 80 printable characters.")
    return value


def _category(value: str) -> str:
    if value not in CATEGORIES:
        raise ValueError("Unknown category.")
    return value


class DemoTransactionIn(DemoModel):
    """A synthetic charge entered by an admin. The id, source and account are always chosen by the server."""
    merchant: str
    category: str
    amount: Decimal = Field(gt=0, le=Decimal("99999.99"), max_digits=7, decimal_places=2)
    occurred_at: AwareDatetime
    direction: Literal["debit", "credit"] = "debit"
    is_subscription: bool = False

    _clean_merchant = field_validator("merchant")(_merchant)
    _clean_category = field_validator("category")(_category)


class DemoTransactionPatch(DemoModel):
    merchant: str | None = None
    category: str | None = None
    amount: Decimal | None = Field(default=None, gt=0, le=Decimal("99999.99"), max_digits=7, decimal_places=2)
    occurred_at: AwareDatetime | None = None
    direction: Literal["debit", "credit"] | None = None
    is_subscription: bool | None = None

    @field_validator("merchant")
    @classmethod
    def _m(cls, value):
        return None if value is None else _merchant(value)

    @field_validator("category")
    @classmethod
    def _c(cls, value):
        return None if value is None else _category(value)

    @model_validator(mode="after")
    def _something(self):
        if not self.model_fields_set:
            raise ValueError("Nothing to change.")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Changed fields cannot be null.")
        return self


class DemoRow(DemoModel):
    id: str
    occurred_at: str
    amount: float
    merchant_display: str
    merchant_category: str
    direction: Literal["debit", "credit", "unknown"]
    is_subscription: bool
    kind: Literal["purchase", "transfer", "deposit", "withdrawal"]
    origin: Literal["baseline", "admin"]
    edited_at: str | None
    # True when the user already decided this charge's alert; such a charge cannot be edited or deleted.
    decided: bool


class DemoStatus(DemoModel):
    enabled: bool
    rows: int
    cap: int


ScenarioName = Literal["duplicate", "large_purchase", "price_hike"]


class ScenarioResult(DemoModel):
    scenario: ScenarioName
    created: list[DemoRow]


class ResetResult(DemoModel):
    restored: int
    cleared_decisions: int
    cleared_memories: int


class DemoLogEntry(DemoModel):
    id: int
    at: str
    action: Literal["create", "update", "delete", "scenario", "reset"]
    tx_id: str | None
    summary: str
