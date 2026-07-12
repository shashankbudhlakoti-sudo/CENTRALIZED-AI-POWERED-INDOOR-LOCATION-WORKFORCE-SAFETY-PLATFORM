// Polls GET /it/device-health - CONFIRMED shape from Shashank (real, built):
// { total_tags, active_tags, low_battery: [tag_id...], possibly_offline: [tag_id...] }
// A summary object with two flat tag_id lists, NOT per-device rows with
// battery_pct/last_seen_at - the earlier version of this hook assumed a
// richer per-device shape that doesn't match what was actually built.
//
// Device-only scope, no employee identity: IT sees tag_id/counts only,
// never which employee a tag belongs to (data minimization, Section 7).
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../auth/apiClient";

const POLL_INTERVAL_MS = 10000;

export function useDeviceHealth() {
  const [summary, setSummary] = useState({ total_tags: 0, active_tags: 0, low_battery: [], possibly_offline: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchOnce() {
      try {
        const data = await apiFetch("/it/device-health");
        if (!cancelled) {
          setSummary(data);
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

  return { summary, loading, error };
}
