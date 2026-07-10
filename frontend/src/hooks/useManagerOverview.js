// Two different reliability tiers in this one hook, worth being explicit
// about:
//
// - alertCount / mismatchCount: built from GET /alerts and GET /checkpoints,
//   which are ALREADY CONFIRMED working (same endpoints AlertFeed and
//   CheckpointViewer use successfully today). These will show real numbers
//   immediately, no backend changes needed.
// - departments: from a PROPOSED GET /manager/department-summaries
//   endpoint, adapted from the scaffold's original TODO comment
//   (GET /api/manager/department-summaries) - NOT yet confirmed with
//   Shashank. Will show an honest error banner if it 404s, independent of
//   the confirmed alert/checkpoint counts above still working fine.
//
// Manager sees organizational summary only (department-level rollups),
// never Security's operational detail (exact coordinates, live map) -
// Section 11 tiering.
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../auth/apiClient";

const POLL_INTERVAL_MS = 15000;

export function useManagerOverview() {
  const [alertCount, setAlertCount] = useState(null);
  const [mismatchCount, setMismatchCount] = useState(null);
  const [departments, setDepartments] = useState([]);
  const [countsError, setCountsError] = useState(null);
  const [departmentsError, setDepartmentsError] = useState(null);
  const [loading, setLoading] = useState(true);
  const pollRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchOnce() {
      // Confirmed-working endpoints - fetched independently of the
      // proposed one below, so a 404 on department-summaries never takes
      // down the real alert/mismatch counts.
      try {
        const [alerts, checkpoints] = await Promise.all([
          apiFetch("/alerts?acknowledged=false"),
          apiFetch("/checkpoints?status=mismatch"),
        ]);
        if (!cancelled) {
          setAlertCount(alerts.length);
          setMismatchCount(checkpoints.length);
          setCountsError(null);
        }
      } catch (err) {
        if (!cancelled) setCountsError(err.message);
      }

      try {
        const data = await apiFetch("/manager/department-summaries");
        if (!cancelled) {
          setDepartments(data);
          setDepartmentsError(null);
        }
      } catch (err) {
        if (!cancelled) setDepartmentsError(err.message);
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

  return { alertCount, mismatchCount, departments, countsError, departmentsError, loading };
}
