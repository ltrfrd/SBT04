// -----------------------------------------------------------
// API Helper (single source of truth for backend base URL)
// -----------------------------------------------------------

// Use Vite env if provided, otherwise default to local backend
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

// -----------------------------------------------------------
// Parse response safely (handles JSON + non-JSON errors)
// -----------------------------------------------------------
async function parseResponse(res) {
  const text = await res.text();                 // Read raw response text
  const isJson = res.headers
    .get("content-type")
    ?.includes("application/json");              // Detect JSON response

  const data = isJson && text ? JSON.parse(text) : text; // Parse if JSON

  if (!res.ok) {                                 // If HTTP error
    const detail = data?.detail ?? data;          // FastAPI often uses {detail: ...}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return data;                                   // Return parsed data
}

// -----------------------------------------------------------
// GET helper
// -----------------------------------------------------------
export async function apiGet(path) {
  const res = await fetch(`${BASE_URL}${path}`, { // Call backend with base URL
    method: "GET",                                // HTTP GET
  });

  return parseResponse(res);                      // Parse and return
}

// -----------------------------------------------------------
// POST helper
// -----------------------------------------------------------
export async function apiPost(path, body) {
  const res = await fetch(`${BASE_URL}${path}`, { // Call backend with base URL
    method: "POST",                               // HTTP POST
    headers: { "Content-Type": "application/json" }, // JSON header
    body: JSON.stringify(body),                   // Convert payload to JSON
  });

  return parseResponse(res);                      // Parse and return
}