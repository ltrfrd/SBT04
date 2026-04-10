# Deferred Features

## 1. Pre-Trip Checklist UI
Status: Deactivated for now  
Decision: Keep backend fields and migration, hide from driver workflow for now  
Reason: Current workflow should stay simpler; checklist audit data can be re-enabled later without schema changes  
Files affected:
- backend/models/pretrip.py
- backend/schemas/pretrip.py
- backend/templates/driver_run.html
- alembic/versions/20260409_add_pretrip_checklist_history.py

Future options:
- Re-enable in driver UI
- Expand checklist items
- Keep as audit-only backend storage

