# -----------------------------------------------------------
# backend/deps/admin.py
# - Admin gating dependency (foundation for RBAC)
# - Temporary implementation: header-based admin token
# - Replace later with real auth (JWT/session) + roles table
# -----------------------------------------------------------

from __future__ import annotations

import os                                                     # env access (ADMIN_TOKEN)
from fastapi import Header, HTTPException, status             # header extraction + errors


# -----------------------------------------------------------
# require_admin
# - Validates admin access for protected endpoints
# - Current rule: X-Admin-Token must match ADMIN_TOKEN
# -----------------------------------------------------------
def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("ADMIN_TOKEN", "")                   # empty => admin disabled unless set
    if not expected or x_admin_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,            # forbidden
            detail="Admin access required",                   # consistent error message
        )