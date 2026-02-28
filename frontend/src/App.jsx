// -----------------------------------------------------------
// React Imports
// -----------------------------------------------------------
import { useEffect, useState } from "react";          // Import React hooks
import { apiGet, apiPost } from "./api";              // Import API helpers


// -----------------------------------------------------------
// Main App Component
// -----------------------------------------------------------
export default function App() {

  // -----------------------------------------------------------
  // State
  // -----------------------------------------------------------
  const [routeId, setRouteId] = useState("1");       // Route ID input
  const [stops, setStops] = useState([]);            // Stops list
  const [error, setError] = useState("");            // Error message


  // -----------------------------------------------------------
  // Load Stops from backend
  // GET /routes/{route_id}/stops
  // -----------------------------------------------------------
  async function loadStops() {
    setError("");                                     // Clear old errors

    try {
      // Call new route-scoped endpoint
      const data = await apiGet(`/routes/${routeId}/stops`);
      setStops(data);                                 // Update stops state
    } catch (e) {
      setError(String(e));                            // Show error if failed
      setStops([]);                                   // Clear stops on error
    }
  }


  // -----------------------------------------------------------
  // Create a test stop
  // POST /stops
  // -----------------------------------------------------------
  async function createTestStop() {
    setError("");                                     // Clear old errors

    try {
      const payload = {
        route_id: Number(routeId),                    // Current route ID
        type: "pickup",                               // Stop type
        name: "Test Stop",
        address: "Test Address",
        latitude: 53.5461,
        longitude: -113.4938,
      };

      await apiPost("/stops", payload);               // Create stop
      await loadStops();                              // Refresh list
    } catch (e) {
      setError(String(e));
    }
  }


  // -----------------------------------------------------------
  // Load stops once on component mount
  // -----------------------------------------------------------
  useEffect(() => {
    loadStops();
  }, []);


  // -----------------------------------------------------------
  // UI Layout
  // -----------------------------------------------------------
  return (
    <div style={{ padding: 20, fontFamily: "Arial" }}>
      <h2>Stops Viewer (Backend Test)</h2>

      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <label>Route ID:</label>

        <input
          value={routeId}
          onChange={(e) => setRouteId(e.target.value)}
          style={{ width: 80 }}
        />

        <button onClick={loadStops}>Load Stops</button>
        <button onClick={createTestStop}>Create Test Stop</button>
      </div>

      {error && <p style={{ color: "red" }}>{error}</p>}

      <pre
        style={{
          marginTop: 20,
          background: "#f4f4f4",
          padding: 10,
          color: "#000",          // Force black text
        }}
  >
    {JSON.stringify(stops, null, 2)}
  </pre>
    </div>
  );
}