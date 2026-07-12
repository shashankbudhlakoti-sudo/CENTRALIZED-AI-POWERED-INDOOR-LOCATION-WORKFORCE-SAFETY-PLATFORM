// HR Panel - real employee roster from GET /employees. RLS already scopes
// this to HR's own department (or all, for security_admin/general_manager),
// so this component trusts what the backend returns rather than
// re-filtering by department client-side.
import { useMemo, useState } from "react";
import { useEmployeeRoster } from "../hooks/useEmployeeRoster";
import styles from "./HRPanel.module.css";

function ConsentBadge({ given }) {
  return (
    <span className={`${styles.badge} ${given ? styles.badgeYes : styles.badgeNo}`}>
      {given ? "Consent on file" : "No consent"}
    </span>
  );
}

function StatusBadge({ active }) {
  return (
    <span className={`${styles.badge} ${active ? styles.badgeActive : styles.badgeInactive}`}>
      {active ? "Active" : "Inactive"}
    </span>
  );
}

export default function HRPanel() {
  const { employees, loading, error, refetch } = useEmployeeRoster();
  const [search, setSearch] = useState("");
  const [showInactive, setShowInactive] = useState(false);

  const filtered = useMemo(() => {
    return employees.filter((e) => {
      if (!showInactive && !e.active) return false;
      if (!search.trim()) return true;
      const q = search.toLowerCase();
      return (
        e.full_name.toLowerCase().includes(q) ||
        e.employee_code.toLowerCase().includes(q) ||
        (e.role_title ?? "").toLowerCase().includes(q)
      );
    });
  }, [employees, search, showInactive]);

  const consentMissingCount = employees.filter((e) => e.active && !e.consent_given).length;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>HR panel</h1>
          <p className={styles.subtitle}>Employee roster and consent status.</p>
        </div>
        <button className={styles.refreshButton} onClick={refetch}>Refresh</button>
      </div>

      {error && <div className={styles.errorBanner}>Couldn't load roster: {error}</div>}

      {!loading && !error && consentMissingCount > 0 && (
        <div className={styles.warningBanner}>
          {consentMissingCount} active employee{consentMissingCount === 1 ? "" : "s"} missing consent on file.
        </div>
      )}

      <div className={styles.controls}>
        <input
          className={styles.searchInput}
          type="text"
          placeholder="Search name, employee code, or title…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label className={styles.checkboxLabel}>
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(e) => setShowInactive(e.target.checked)}
          />
          Show inactive
        </label>
      </div>

      {loading && <div className={styles.emptyState}>Loading roster…</div>}

      {!loading && !error && filtered.length === 0 && (
        <div className={styles.emptyState}>No employees match your search.</div>
      )}

      {!loading && filtered.length > 0 && (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Employee</th>
              <th>Code</th>
              <th>Department</th>
              <th>Title</th>
              <th>Status</th>
              <th>Consent</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => (
              <tr key={e.id}>
                <td>
                  <div className={styles.nameCell}>{e.full_name}</div>
                  <div className={styles.emailCell}>{e.email}</div>
                </td>
                <td>{e.employee_code}</td>
                <td>{e.department}</td>
                <td>{e.role_title ?? "—"}</td>
                <td><StatusBadge active={e.active} /></td>
                <td><ConsentBadge given={e.consent_given} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className={styles.footer}>{filtered.length} of {employees.length} employees shown</div>
    </div>
  );
}
