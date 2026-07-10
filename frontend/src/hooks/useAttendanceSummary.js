// Polls a PROPOSED GET /hr/attendance-summary endpoint - not yet confirmed
// with Shashank. Path adapted from the scaffold's original TODO comment
// (GET /api/hr/attendance-summary) to match the real /api/v1 prefix.
//
// Aggregated-only scope: HR sees zone-time summaries and shift compliance,
// never raw (x,y) coordinates or checkpoint photos (data minimization,
// Section 7) - this endpoint should already return aggregates, not raw
// position_events rows.
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../auth/apiClient";

const POLL_INTERVAL_MS = 15000;

export function useAttendanceSummary() {
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchOnce() {
      try {
        const data = await apiFetch("/hr/attendance-summary");
        if (!cancelled) {
          setEmployees(data);
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

  return { employees, loading, error };
}
