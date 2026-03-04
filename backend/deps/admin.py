# ===========================================================
# backend/deps/admin.py — Admin Dependency (SBT01)
# -----------------------------------------------------------
# Responsibilities:
#   - Gate protected endpoints
#   - Validate admin token via request header
#   - Provide clean upgrade path to JWT/role-based auth
# ===========================================================

from __future__ import annotations  # Forward refs for typing

# -----------------------------------------------------------
# Standard library
# -----------------------------------------------------------
import os  # Environment variables

# -----------------------------------------------------------
# FastAPI
# -----------------------------------------------------------
from fastapi import Header  # Extract header value
from fastapi import HTTPException  # Raise HTTP errors
from fastapi import status  # HTTP status codes


# -----------------------------------------------------------
# require_admin
# - Validates X-Admin-Token header
# - Compares against ADMIN_TOKEN from environment
# - Returns 403 if invalid or not configured
# -----------------------------------------------------------
def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected_token = os.getenv("ADMIN_TOKEN", "")  # Read token from environment

    # -------------------------------------------------------
    # If ADMIN_TOKEN not configured → deny access
    # -------------------------------------------------------
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,  # Forbidden
            detail="Admin access not configured",
        )

    # -------------------------------------------------------
    # If token mismatch → deny access
    # -------------------------------------------------------
    if x_admin_token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,  # Forbidden
            detail="Admin access required",
        )
