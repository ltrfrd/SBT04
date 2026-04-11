# -----------------------------------------------------------
# Reports Router Compatibility
# - Keep legacy imports working while reports is the app layer
# -----------------------------------------------------------
from .reports import router  # Re-export reports router during the rename phase


__all__ = ["router"]  # Preserve legacy router export
