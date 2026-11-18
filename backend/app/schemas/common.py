from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    message: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class HealthResponse(BaseModel):
    status: str = "ok"
    app_name: str
    environment: str
    database_status: str
    market_provider: str
    ollama_status: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SystemConfigResponse(BaseModel):
    app_name: str
    environment: str
    api_version: str = "v1"
    market_provider: str
    ollama_enabled: bool
    ollama_model: str
    initial_equity: float
    initial_cash: float
