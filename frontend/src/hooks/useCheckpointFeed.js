// Polls GET /checkpoints per the API contract. Polling rather than
// WebSocket for now, since checkpoint events are lower-frequency than
// position updates (LiveMap already owns the WebSocket connection) -
// keeps this independent and simple rather than sharing a socket
// connection across unrelated concerns.
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../auth/apiClient";

const POLL_INTERVAL_MS = 5000;

export function useCheckpointFeed(statusFilter = null) {
  const [checkpoints, setCheckpoints] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchOnce() {
      try {
        const query = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
        const data = await apiFetch(`/checkpoints${query}`);
        if (!cancelled) {
          setCheckpoints(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchOnce();
    pollRef.current = setInterval(fetchOnce, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(pollRef.current);
    };
  }, [statusFilter]);

  return { checkpoints, loading, error };
}
