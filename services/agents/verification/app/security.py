"""Pluggable authentication dependency for protected verification endpoints."""

import hmac
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader


api_key_header = APIKeyHeader(name="X-KAVACH-API-Key", auto_error=False)


def require_principal(x_kavach_api_key: str | None = Depends(api_key_header)) -> dict:
    """Development API-key stub; replaceable with the project's JWT/RBAC provider."""
    expected = os.getenv("KAVACH_API_KEY")
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Authentication is not configured.")
    if not x_kavach_api_key or not hmac.compare_digest(x_kavach_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized.")
    return {"subject": "api-key", "roles": ["verification:request"]}
