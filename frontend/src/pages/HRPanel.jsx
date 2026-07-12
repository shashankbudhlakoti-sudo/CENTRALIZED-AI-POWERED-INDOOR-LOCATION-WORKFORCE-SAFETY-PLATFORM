// HR Panel - sees aggregated attendance summaries only, never raw position
// coordinates or checkpoint photos (Section 7 data minimization).
//
// Real endpoint (GET /hr/attendance-summary, verified against main.py)
// returns department-level present-today counts only - no per-employee
// zone-time breakdown exists, so this is a simple table, not the
// per-employee shift-bar visualization originally assumed.
import { useAttendanceSummary } from "../hooks/useAttendanceSummary";
import styles from "./OpsPanel.module.css";

export default function HRPanel() {
  const { departments, loading, error } = useAttendanceSummary();

  const totalPresent = departments.reduce((sum, d) => sum + (d.present_today ?? 0), 0);

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>HR panel</h1>
        <p className={styles.subtitle}>
          Attendance derived from badge activity, zone time summaries, shift compliance.
        </p>
      </div>

      <div className={styles.summaryRow}>
        <div className={styles.summaryCard}>
          <div className={styles.summaryLabel}>Present today (all departments)</div>
          <div className={styles.summaryValue}>{totalPresent}</div>
        </div>
        <div className={styles.summaryCard}>
          <div className={styles.summaryLabel}>Departments reporting</div>
          <div className={styles.summaryValue}>{departments.length}</div>
        </div>
      </div>

      {error && (
        <div className={styles.errorBanner}>
          Couldn't load attendance summary: {error}
        </div>
      )}

      {loading && departments.length === 0 && !error && (
        <div className={styles.emptyState}>Loading attendance summary…</div>
      )}

      {!loading && departments.length === 0 && !error && (
        <div className={styles.emptyState}>No attendance data yet.</div>
      )}

      {departments.length > 0 && (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Department</th>
              <th style={{ textAlign: "right" }}>Present today</th>
            </tr>
          </thead>
          <tbody>
            {departments.map((d) => (
              <tr key={d.department}>
                <td>{d.department}</td>
                <td className={styles.mono} style={{ textAlign: "right" }}>{d.present_today}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
