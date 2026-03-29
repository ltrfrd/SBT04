warning: in the working copy of 'backend/routers/run.py', LF will be replaced by CRLF the next time Git touches it
[1mdiff --git a/backend/routers/run.py b/backend/routers/run.py[m
[1mindex 76528c6..45f85fa 100644[m
[1m--- a/backend/routers/run.py[m
[1m+++ b/backend/routers/run.py[m
[36m@@ -274,7 +274,7 @@[m [mdef create_run(run: RunStart, db: Session = Depends(get_db)):[m
     new_run = run_model.Run([m
         driver_id=resolved_driver_id,                            # Assigned driver[m
         route_id=run.route_id,                                   # Linked route[m
[31m-        run_type=run.run_type,                                   # Run type (AM/PM/etc.)[m
[32m+[m[32m        run_type=run.run_type,                                   # Flexible run label[m
         start_time=None,                                         # Not started yet[m
         end_time=None,                                           # Not ended yet[m
         current_stop_id=None,                                    # No active stop[m
[36m@@ -285,6 +285,7 @@[m [mdef create_run(run: RunStart, db: Session = Depends(get_db)):[m
     db.commit()                                                  # Persist to DB[m
     db.refresh(new_run)                                          # Reload instance[m
     return _serialize_run(new_run)                               # Return response[m
[32m+[m
 # -----------------------------------------------------------[m
 # - Start run[m
 # - Start a run, copy stops, and create runtime assignments[m
[36m@@ -567,27 +568,6 @@[m [mdef end_run_by_driver([m
 [m
     return active_run                               # Return ended run[m
 [m
[31m-# =============================================================================[m
[31m-# GET /runs/[m
[31m-# ---------------------------------------------------------------------------[m
[31m-# Returns a list of runs.[m
[31m-#[m
[31m-# Supports optional filters:[m
[31m-#   - driver_id  → filter runs belonging to a specific driver[m
[31m-#   - route_id   → filter runs belonging to a specific route[m
[31m-#   - run_type   → filter runs by type (ex: AM, PM)[m
[31m-#   - active     → filter runs by current active status[m
[31m-#[m
[31m-# Notes:[m
[31m-#   active=True   → runs where start_time IS NOT NULL and end_time IS NULL[m
[31m-#   active=False  → runs that are not currently active (planned or ended)[m
[31m-#[m
[31m-# If no filters are provided, all runs are returned.[m
[31m-#[m
[31m-# Enriched fields returned:[m
[31m-#   - driver_name[m
[31m-#   - route_number[m
[31m-# =============================================================================[m
 # -----------------------------------------------------------[m
 # - List runs by route[m
 # - Return only runs that belong to the selected route[m
[36m@@ -879,29 +859,15 @@[m [mdef advance_to_next_stop([m
 [m
     return run                                      # Return updated run[m
 [m
[31m-# =============================================================================[m
[31m-# POST /runs/{run_id}/pickup_student[m
[31m-# -----------------------------------------------------------------------------[m
[31m-# Mark a student as picked up during an active run.[m
[31m-#[m
[31m-# Purpose:[m
[31m-#   - confirm boarding at the current stop[m
[31m-#   - store pickup timestamp[m
[31m-#   - mark student as onboard[m
[31m-#[m
[31m-# Validation:[m
[31m-#   - run must exist[m
[31m-#   - run must be started / active[m
[31m-#   - run must currently be at a stop[m
[31m-#   - student must be assigned to this run[m
[31m-#   - student's assigned stop must match current stop sequence[m
[31m-#   - student must not already be picked up[m
[31m-# =============================================================================[m
[32m+[m[32m# -----------------------------------------------------------[m
[32m+[m[32m# - Pick up student[m
[32m+[m[32m# - Record boarding at the run's current actual stop[m
[32m+[m[32m# -----------------------------------------------------------[m
 @router.post([m
     "/{run_id}/pickup_student",[m
     response_model=PickupStudentResponse,[m
     summary="Pick up student",[m
[31m-    description="Mark a student as picked up at the run's current stop and log a PICKUP event.",[m
[32m+[m[32m    description="Mark a student as picked up at the run's current actual stop and log a PICKUP event.",[m
     response_description="Pickup confirmation",[m
 )[m
 def pickup_student([m
[36m@@ -949,10 +915,9 @@[m [mdef pickup_student([m
     # -------------------------------------------------------------------------[m
     # Load the student assignment for this run[m
     # -------------------------------------------------------------------------[m
[31m-    # joinedload() is used so the assigned stop is available immediately.[m
     assignment = ([m
         db.query(StudentRunAssignment)[m
[31m-        .options(joinedload(StudentRunAssignment.stop))[m
[32m+[m[32m        .options(joinedload(StudentRunAssignment.stop))  # Load assigned stop context for runtime views[m
         .filter([m
             StudentRunAssignment.run_id == run_id,[m
             StudentRunAssignment.student_id == payload.student_id,[m
[36m@@ -976,7 +941,7 @@[m [mdef pickup_student([m
         )[m
 [m
     # -------------------------------------------------------------------------[m
[31m-    # Mark pickup fields[m
[32m+[m[32m    # Mark pickup fields using the current actual stop[m
     # -------------------------------------------------------------------------[m
     now = datetime.now(timezone.utc)  # Current UTC timestamp (timezone-aware)[m
     [m
[36m@@ -987,7 +952,7 @@[m [mdef pickup_student([m
 [m
     # -----------------------------------------------------------[m
     # Log pickup event[m
[31m-    # - Records actual stop used for dropoff[m
[32m+[m[32m    # - Records actual stop used for pickup[m
     # -----------------------------------------------------------[m
     event = RunEvent([m
         run_id=run.id,[m
[36m@@ -1015,30 +980,15 @@[m [mdef pickup_student([m
         picked_up_at=assignment.picked_up_at,[m
     )[m
 [m
[31m-# =============================================================================[m
[31m-# POST /runs/{run_id}/dropoff_student[m
[31m-# -----------------------------------------------------------------------------[m
[31m-# Mark a student as dropped off during an active run.[m
[31m-#[m
[31m-# Purpose:[m
[31m-#   - confirm drop-off at the current stop[m
[31m-#   - store drop-off timestamp[m
[31m-#   - mark student as no longer onboard[m
[31m-#[m
[31m-# Validation:[m
[31m-#   - run must exist[m
[31m-#   - run must be started / active[m
[31m-#   - run must currently be at a stop[m
[31m-#   - student must be assigned to this run[m
[31m-#   - student's assigned stop must match current stop sequence[m
[31m-#   - student must currently be onboard[m
[31m-#   - student must not already be dropped off[m
[31m-# =============================================================================[m
[32m+[m[32m# -----------------------------------------------------------[m
[32m+[m[32m# - Drop off student[m
[32m+[m[32m# - Record drop-off at the run's current actual stop[m
[32m+[m[32m# -----------------------------------------------------------[m
 @router.post([m
     "/{run_id}/dropoff_student",[m
     response_model=DropoffStudentResponse,[m
     summary="Drop off student",[m
[31m-    description="Mark a student as dropped off at the run's current stop and log a DROPOFF event.",[m
[32m+[m[32m    description="Mark a student as dropped off at the run's current actual stop and log a DROPOFF event.",[m
     response_description="Drop-off confirmation",[m
 )[m
 def dropoff_student([m
[36m@@ -1088,11 +1038,11 @@[m [mdef dropoff_student([m
         )[m
 [m
     # -------------------------------------------------------------------------[m
[31m-    # Load the student's runtime assignment and assigned stop[m
[32m+[m[32m    # Load the student's runtime assignment[m
     # -------------------------------------------------------------------------[m
     assignment = ([m
         db.query(StudentRunAssignment)[m
[31m-        .options(joinedload(StudentRunAssignment.stop))[m
[32m+[m[32m        .options(joinedload(StudentRunAssignment.stop))  # Load assigned stop context for runtime views[m
         .filter([m
             StudentRunAssignment.run_id == run_id,[m
             StudentRunAssignment.student_id == payload.student_id,[m
[36m@@ -1125,7 +1075,7 @@[m [mdef dropoff_student([m
         )[m
 [m
     # -------------------------------------------------------------------------[m
[31m-    # Mark drop-off fields[m
[32m+[m[32m    # Mark drop-off fields using the current actual stop[m
     # -------------------------------------------------------------------------[m
     now = datetime.now(timezone.utc)  # Current UTC timestamp (timezone-aware)[m
 [m
[36m@@ -2013,6 +1963,7 @@[m [mdef get_run_summary(run_id: int, db: Session = Depends(get_db)):[m
         db.query(StudentRunAssignment)[m
         .filter(StudentRunAssignment.run_id == run_id)[m
     ), run).all()  # Exclude planned absences from summary counts[m
[32m+[m[32m    occupancy_counts = _build_run_occupancy_counts(assignments)  # Reuse shared onboard/load counts[m
 [m
     # -------------------------------------------------------------------------[m
     # Determine run status[m
[36m@@ -2027,7 +1978,7 @@[m [mdef get_run_summary(run_id: int, db: Session = Depends(get_db)):[m
     # -------------------------------------------------------------------------[m
     # Compute current load[m
     # -------------------------------------------------------------------------[m
[31m-    current_load = len(assignments)[m
[32m+[m[32m    current_load = occupancy_counts["total_currently_onboard"]  # Current load means students onboard now[m
 [m
     # -------------------------------------------------------------------------[m
     # Return summary[m
[36m@@ -2046,3 +1997,4 @@[m [mdef get_run_summary(run_id: int, db: Session = Depends(get_db)):[m
         total_assigned_students=len(assignments),[m
         current_load=current_load,[m
     )[m
[41m+[m
