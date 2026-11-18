from typing import Any


class HedgeLabError(Exception):
    """Base exception class for HedgeLab application errors."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR", details: Any | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details


class ResourceNotFoundError(HedgeLabError):
    def __init__(self, message: str, details: Any | None = None):
        super().__init__(message, code="RESOURCE_NOT_FOUND", details=details)


class RiskRejectionError(HedgeLabError):
    def __init__(self, message: str, details: Any | None = None):
        super().__init__(message, code="RISK_REJECTION", details=details)


class OrderExecutionError(HedgeLabError):
    def __init__(self, message: str, details: Any | None = None):
        super().__init__(message, code="ORDER_EXECUTION_ERROR", details=details)


class InvalidScenarioError(HedgeLabError):
    def __init__(self, message: str, details: Any | None = None):
        super().__init__(message, code="INVALID_SCENARIO", details=details)


class ProviderError(HedgeLabError):
    def __init__(self, message: str, details: Any | None = None):
        super().__init__(message, code="PROVIDER_ERROR", details=details)
