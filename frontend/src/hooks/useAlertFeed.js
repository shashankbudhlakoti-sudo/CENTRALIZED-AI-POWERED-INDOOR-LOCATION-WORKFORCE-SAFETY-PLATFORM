// Polls GET /alerts?acknowledged=false per the API contract, and exposes
// an acknowledge() action that calls POST /alerts/{id}/acknowledge.
// Same independent-polling pattern as useCheckpointFeed - alerts are
// lower-frequency than live position updates, so this doesn't need to
// share LiveMap's WebSocket connection.
import { useEffect, useRef, useState, useCallback } from "react";
import { apiFetch } from "../auth/apiClient";

const POLL_INTERVAL_MS = 4000;

export function useAlertFeed() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  const fetchOnce = useCallback(async () => {
    try {
      const data = await apiFetch("/alerts?acknowledged=false");
      setAlerts(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOnce();
    pollRef.current = setInterval(fetchOnce, POLL_INTERVAL_MS);
    return () => clearInterval(pollRef.current);
  }, [fetchOnce]);

  const acknowledge = useCallback(async (alertId, note = "") => {
    // Optimistic update: remove immediately from the list so the UI feels
    // instant, but re-fetch right after to reconcile with the server in
    // case the acknowledge call actually failed.
    setAlerts((prev) => prev.filter((a) => a.id !== alertId));
    try {
      await apiFetch(`/alerts/${alertId}/acknowledge`, {
        method: "POST",
        body: JSON.stringify({ note }),
      });
    } catch (err) {
      setError(`Failed to acknowledge alert: ${err.message}`);
    } finally {
      fetchOnce();
    }
  }, [fetchOnce]);

  return { alerts, loading, error, acknowledge };
}
