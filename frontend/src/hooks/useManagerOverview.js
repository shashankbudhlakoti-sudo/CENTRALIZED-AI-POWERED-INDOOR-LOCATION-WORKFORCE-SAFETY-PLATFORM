// Two different reliability tiers, worth being explicit about:
//
// - alertCount / mismatchCount: built from GET /alerts and GET /checkpoints,
//   already confirmed working (same endpoints AlertFeed/CheckpointViewer use).
// - departments: from GET /manager/department-summaries - CONFIRMED shape
//   from main.py (real, verified against actual route code):
//   { departments: [{ department, employee_count, open_alerts }] }
//   No manager_name or avg_attendance_pct - those fields don't exist in
//   the real endpoint, the earlier assumption included fields that aren't
//   actually returned.
//
// Manager sees organizational summary only (department-level rollups),
// never Security's operational detail (exact coordinates, live map).
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
          setDepartments(data.departments ?? []);
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
