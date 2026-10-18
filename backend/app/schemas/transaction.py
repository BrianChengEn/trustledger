from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class Transaction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    occurred_at: AwareDatetime
    amount: float = Field(ge=0, allow_inf_nan=False)
    currency: Literal["USD"]
    direction: Literal["debit", "credit"]
    merchant_display: str = Field(max_length=80)
    merchant_category: str = Field(max_length=40)
    source: Literal["synthetic", "nessie"]
    account_token: str = Field(pattern=r"^acct_[A-Za-z0-9_-]+$")
    is_subscription: bool

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value):
        if value.utcoffset() is None:
            raise ValueError("Transaction timestamps require a timezone.")
        return value
