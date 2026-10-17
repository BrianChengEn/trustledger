from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Transaction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    occurred_at: AwareDatetime
    amount: float = Field(ge=0)
    currency: Literal["USD"]
    direction: Literal["debit", "credit"]
    merchant_display: str = Field(max_length=80)
    merchant_category: str = Field(max_length=40)
    source: Literal["synthetic", "nessie"]
    account_token: str = Field(pattern=r"^acct_[A-Za-z0-9_-]+$")
    is_subscription: bool
