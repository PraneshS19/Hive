from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    symbol: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9&.-]{0,19}$")
    side: Literal["BUY", "SELL"]
    requested: int = Field(gt=0, strict=True, le=1_000_000_000)
    price: float = Field(gt=0, allow_inf_nan=False)

    auto_execute: bool = True
    reason: str | None = "Manual simulated order"


class OrderResponse(BaseModel):
    id: int
    symbol: str
    side: str
    requested: int
    executed: int
    price: float
    fee: float
    status: str  # PROPOSAL, APPROVED, RESIZED, REJECTED, FILLED, CANCELLED
    reason: str
    time: str
    created_at: datetime


class ExecutionResponse(BaseModel):
    id: int
    order_id: int
    symbol: str
    side: str
    quantity: int
    price: float
    fee: float
    timestamp: datetime


class LedgerEntryResponse(BaseModel):
    id: int
    transaction_type: str
    amount: float
    balance_after: float
    description: str
    reference_id: str
    created_at: datetime
