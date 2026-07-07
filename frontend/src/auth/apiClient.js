// Thin fetch wrapper that attaches the current in-memory token to every
// request and centralizes 401 handling. No API keys or credentials ever
// live in this file - only the short-lived Keycloak access token.
import { getToken } from "./keycloak";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

export async function apiFetch(path, options = {}) {
  const token = getToken();

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  });

  if (response.status === 401) {
    // Token rejected server-side - force fresh login rather than showing
    // a confusing partial UI state.
    window.location.reload();
    throw new Error("Session expired");
  }

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`API error ${response.status}: ${body}`);
  }

  return response.json();
}
