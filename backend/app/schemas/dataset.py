"""Persisted source contract; existing product DTOs remain compatible."""
from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class BankSimFeatures(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    customer_code: str = Field(min_length=1, max_length=80)
    merchant_code: str = Field(min_length=1, max_length=80)
    age_band: str | None = Field(default=None, max_length=20)
    gender: str | None = Field(default=None, max_length=20)
    zipcode_origin: str | None = Field(default=None, max_length=20)
    zipcode_merchant: str | None = Field(default=None, max_length=20)


class TransactionRecord(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    id: str = Field(min_length=1, max_length=100)
    owner: str = Field(min_length=1, max_length=512)
    source: Literal['nessie', 'banksim']
    dataset_id: str = Field(min_length=1, max_length=100)
    source_record_key: str = Field(min_length=1, max_length=100)
    customer_token: str | None = None
    account_token: str | None = None
    amount_minor: int = Field(strict=True, ge=0, le=9007199254740991)
    currency: str | None = Field(default=None, pattern=r'^[A-Z]{3}$')
    kind: Literal['purchase', 'transfer', 'deposit', 'withdrawal', 'unknown'] = 'unknown'
    direction: Literal['debit', 'credit', 'unknown'] = 'unknown'
    merchant_token: str | None = None
    merchant_display: str | None = Field(default=None, max_length=80)
    merchant_category: str | None = Field(default=None, max_length=40)
    source_category: str | None = Field(default=None, max_length=40)
    occurred_at: AwareDatetime | None = None
    occurred_date: date | None = None
    simulation_step: int | None = Field(default=None, strict=True, ge=0)
    is_subscription: bool | None = Field(default=None, strict=True)
    settlement_status: Literal['pending', 'completed', 'cancelled'] | None = None
    banksim_features: BankSimFeatures | None = None

    @model_validator(mode='after')
    def source_semantics(self):
        if sum(value is not None for value in
               (self.occurred_at, self.occurred_date, self.simulation_step)) > 1:
            raise ValueError('Time representations must be exclusive.')
        if self.source == 'banksim':
            if self.simulation_step is None:
                raise ValueError('BankSim requires a simulation step, not a timestamp.')
        elif self.simulation_step is not None or self.banksim_features is not None:
            raise ValueError('Nessie cannot contain BankSim features.')
        return self


class AnalysisRun(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    run_id: str = Field(min_length=1, max_length=100)
    dataset_id: str = Field(min_length=1, max_length=100)
    provider: Literal['rules-only', 'jev', 'rules+jev', 'research-model']
    model_version: str | None = Field(max_length=100)
    positive_mapping: str = Field(min_length=1, max_length=200)
    created_at: AwareDatetime


class Prediction(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    run_id: str
    owner: str
    transaction_id: str
    predicted_positive: bool | None = Field(strict=True)
    score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False, strict=True)
    status: Literal['success', 'degraded', 'failed'] = 'success'

    @model_validator(mode='after')
    def outcome(self):
        if (self.status == 'success') != (self.predicted_positive is not None):
            raise ValueError('Only successful inference has a binary prediction.')
        if self.status != 'success' and self.score is not None:
            raise ValueError('Failed inference cannot carry a score.')
        return self


class HumanReview(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    owner: str
    transaction_id: str
    decision: Literal['normal', 'review']
    consent: bool = Field(strict=True)
    reviewed_at: AwareDatetime
