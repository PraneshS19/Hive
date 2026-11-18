"""
Security utilities and validation helpers for HedgeLab.
Maintains safety guards against untrusted inputs, prompt injection, and arbitrary code execution.
"""
import re
from hmac import compare_digest

from app.core.config import settings
from fastapi import Header, HTTPException


def sanitize_ticker(ticker: str) -> str:
    """Ensure ticker symbol consists only of alphanumeric characters."""
    clean = re.sub(r"[^A-Za-z0-9]", "", ticker).upper()
    if not clean or len(clean) > 10:
        raise ValueError(f"Invalid ticker symbol: '{ticker}'")
    return clean


def sanitize_text(text: str, max_length: int = 1000) -> str:
    """Sanitize free text input to prevent injection attacks."""
    if not text:
        return ""
    clean = text.strip()[:max_length]
    return clean


def require_operator(x_hive_operator_token: str = Header(default="")) -> str:
    configured = settings.HIVE_OPERATOR_TOKEN
    if not configured:
        raise HTTPException(503, "Configure HIVE_OPERATOR_TOKEN to enable operator actions.")
    if not compare_digest(x_hive_operator_token.encode(), configured.encode()):
        raise HTTPException(403, "A valid local operator token is required.")
    return "local-token-operator"
