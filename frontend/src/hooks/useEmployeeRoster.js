// Fetches GET /employees - shape confirmed directly from backend/app/main.py's
// list_employees, not guessed: id, employee_code, full_name, department,
// role_title, email, consent_given, active. RLS on the backend already
// scopes this to the caller's department (or all departments for
// security_admin/general_manager), so no client-side filtering needed.
import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "../auth/apiClient";

export function useEmployeeRoster() {
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchOnce = useCallback(async () => {
    try {
      const data = await apiFetch("/employees");
      setEmployees(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOnce();
    // Roster changes rarely compared to positions/alerts - a slower
    // poll interval is appropriate here, not the 4-5s used elsewhere.
    const interval = setInterval(fetchOnce, 30000);
    return () => clearInterval(interval);
  }, [fetchOnce]);

  return { employees, loading, error, refetch: fetchOnce };
}
