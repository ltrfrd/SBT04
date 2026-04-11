# ===========================================================
# backend/config.py - App Settings
# -----------------------------------------------------------
# Responsibilities:
#   - Centralize environment-driven settings
#   - Keep dev flags (DEBUG) in one place
#   - Provide a single `settings` object for imports
# ===========================================================

from __future__ import annotations  # Forward refs for typing

# -----------------------------------------------------------
# Standard library
# -----------------------------------------------------------
import os  # Environment variables


# -----------------------------------------------------------
# Settings
# -----------------------------------------------------------
class Settings:
    # -------------------------------------------------------
    # DEBUG
    # - true  => dev-only endpoints allowed
    # - false => dev-only endpoints blocked
    # -------------------------------------------------------
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"  # Default true for dev

    # -------------------------------------------------------
    # ENV
    # - Optional environment name (dev/staging/prod)
    # -------------------------------------------------------
    ENV: str = os.getenv("ENV", "dev")  # Default environment label


# -----------------------------------------------------------
# Singleton settings instance
# - Import as: from backend.config import settings
# -----------------------------------------------------------
settings = Settings()  # Create settings once
