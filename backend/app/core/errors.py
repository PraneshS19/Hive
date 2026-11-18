from typing import Any


class HiveError(Exception):
    """Base exception class for HIVE application errors."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR", details: Any | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details


class ResourceNotFoundError(HiveError):
    def __init__(self, message: str, details: Any | None = None):
        super().__init__(message, code="RESOURCE_NOT_FOUND", details=details)


class RiskRejectionError(HiveError):
    def __init__(self, message: str, details: Any | None = None):
        super().__init__(message, code="RISK_REJECTION", details=details)


class OrderExecutionError(HiveError):
    def __init__(self, message: str, details: Any | None = None):
        super().__init__(message, code="ORDER_EXECUTION_ERROR", details=details)


class InvalidScenarioError(HiveError):
    def __init__(self, message: str, details: Any | None = None):
        super().__init__(message, code="INVALID_SCENARIO", details=details)


class ProviderError(HiveError):
    def __init__(self, message: str, details: Any | None = None):
        super().__init__(message, code="PROVIDER_ERROR", details=details)
