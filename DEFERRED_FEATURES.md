# Deferred Features

## 1. Pre-Trip Checklist UI
Status: Deferred / Deactivated
Decision: Hidden from all user-facing workflow; backend support retained
Reason: Keep the driver workflow simpler for now while preserving future inspection-audit flexibility
Backend state: Fields, schema support, migration, and stored data are retained for future re-enable
Files affected:
- backend/models/pretrip.py
- backend/schemas/pretrip.py
- backend/routers/pretrip.py
- backend/templates/driver_run.html
- alembic/versions/20260409_add_pretrip_checklist_history.py

Future options:
- Re-enable in driver workflow
- Keep backend-only
- Expand later into richer inspection auditing

