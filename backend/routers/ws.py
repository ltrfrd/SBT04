# ===========================================================
# backend/routers/ws.py - SBT WebSocket Router
# -----------------------------------------------------------
# Real-time GPS websocket endpoint and connection state
# ===========================================================

import json
from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from database import get_db
from backend.utils import gps_tools


router = APIRouter()


# -----------------------------------------------------------
# WEBSOCKET TRACKING
# -----------------------------------------------------------
# Active WebSocket connections per run_id (real-time GPS broadcasting)
active_connections: Dict[int, List[WebSocket]] = {}


# -----------------------------------------------------------
# WEBSOCKET: GPS + ALERTS
# -----------------------------------------------------------
@router.websocket("/ws/gps/{run_id}")
async def websocket_gps_endpoint(websocket: WebSocket, run_id: int, db: Session = Depends(get_db)):
    """Handles real-time GPS data via WebSocket connections."""
    await websocket.accept()
    if run_id not in active_connections:
        active_connections[run_id] = []
    active_connections[run_id].append(websocket)

    try:
        while True:
            # Receive GPS coordinates from client
            data = await websocket.receive_text()
            gps = json.loads(data)

            # Validate coordinates
            if not gps_tools.validate_gps(gps["lat"], gps["lng"]):
                continue

            # Prepare broadcast payload
            broadcast_data = {
                "run_id": run_id,
                "lat": gps["lat"],
                "lng": gps["lng"],
                "timestamp": datetime.now().isoformat(),
                "progress": gps_tools.get_current_stop_progress(db, run_id, gps["lat"], gps["lng"])
            }

            # Append any nearby stop alerts
            alerts = gps_tools.get_approaching_alerts(db, run_id, gps["lat"], gps["lng"])
            if alerts:
                broadcast_data["alerts"] = alerts

            # Send update to all connected clients on same run_id
            for client in list(active_connections.get(run_id, [])):
                try:
                    await client.send_json(broadcast_data)
                except:
                    # Remove disconnected clients
                    if client in active_connections[run_id]:
                        active_connections[run_id].remove(client)

    except WebSocketDisconnect:
        # Clean disconnect: remove socket safely
        if run_id in active_connections and websocket in active_connections[run_id]:
            active_connections[run_id].remove(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
