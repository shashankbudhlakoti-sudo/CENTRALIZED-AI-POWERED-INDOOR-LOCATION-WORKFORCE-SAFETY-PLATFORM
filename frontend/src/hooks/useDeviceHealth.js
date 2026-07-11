// Polls a PROPOSED GET /it/device-health endpoint - not yet confirmed with
// Shashank. Path adapted from the scaffold's original TODO comment
// (GET /api/it/device-health) to match the real /api/v1 prefix confirmed
// working for positions/alerts/checkpoints. If this 404s, that just means
// the endpoint doesn't exist under this exact path yet - the panel will
// show an honest error banner rather than fail silently (see apiClient.js).
//
// Device-only scope, no employee identity: IT sees tag_uid/battery/uptime,
// never which employee a tag belongs to (data minimization, Section 7).
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../auth/apiClient";

const POLL_INTERVAL_MS = 10000;

export function useDeviceHealth() {
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchOnce() {
      try {
        const data = await apiFetch("/it/device-health");
        if (!cancelled) {
          setDevices(data);
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
  }, []);

  return { devices, loading, error };
}
