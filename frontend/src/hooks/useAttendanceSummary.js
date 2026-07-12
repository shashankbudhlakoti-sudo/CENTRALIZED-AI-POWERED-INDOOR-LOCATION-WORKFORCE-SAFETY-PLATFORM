// Polls GET /hr/attendance-summary - CONFIRMED shape from main.py (real,
// verified against actual route code, not a relayed description):
// { present_by_department: [{ department, present_today }] }
//
// Department-level counts only, never raw coordinates or per-employee
// detail (data minimization, Section 7) - matches what the real endpoint
// actually returns, not the earlier per-employee shift-bar assumption.
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../auth/apiClient";

const POLL_INTERVAL_MS = 15000;

export function useAttendanceSummary() {
  const [departments, setDepartments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchOnce() {
      try {
        const data = await apiFetch("/hr/attendance-summary");
        if (!cancelled) {
          setDepartments(data.present_by_department ?? []);
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

  return { departments, loading, error };
}
