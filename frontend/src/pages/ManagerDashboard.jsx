// General Manager dashboard - Tier 4, organizational visibility
// (department summaries, manager directory) rather than Security's
// operational visibility (exact coordinates, live map) - Section 11.
//
// Real endpoint (GET /manager/department-summaries, verified against
// main.py) returns { departments: [{ department, employee_count,
// open_alerts }] } - no manager_name or avg_attendance_pct field exists,
// those were an earlier unverified assumption.
import { useManagerOverview } from "../hooks/useManagerOverview";
import styles from "./OpsPanel.module.css";

export default function ManagerDashboard() {
  const { alertCount, mismatchCount, departments, countsError, departmentsError, loading } =
    useManagerOverview();

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>Manager dashboard</h1>
        <p className={styles.subtitle}>
          All-department summaries and manager directory with drill-in access.
        </p>
      </div>

      {countsError ? (
        <div className={styles.errorBanner}>Couldn't load live counts: {countsError}</div>
      ) : (
        <div className={styles.summaryRow}>
          <div className={styles.summaryCard}>
            <div className={styles.summaryLabel}>Active alerts (org-wide)</div>
            <div className={`${styles.summaryValue} ${alertCount > 0 ? styles.warn : styles.ok}`}>
              {alertCount ?? "—"}
            </div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryLabel}>Checkpoint mismatches</div>
            <div className={`${styles.summaryValue} ${mismatchCount > 0 ? styles.critical : styles.ok}`}>
              {mismatchCount ?? "—"}
            </div>
          </div>
        </div>
      )}

      <h2 style={{ fontSize: 14, color: "#7B879E", textTransform: "uppercase", letterSpacing: "0.06em", margin: "8px 0 12px" }}>
        Department summaries
      </h2>

      {departmentsError && (
        <div className={styles.errorBanner}>
          Couldn't load department summaries: {departmentsError}
        </div>
      )}

      {loading && departments.length === 0 && !departmentsError && (
        <div className={styles.emptyState}>Loading department summaries…</div>
      )}

      {!loading && departments.length === 0 && !departmentsError && (
        <div className={styles.emptyState}>No department data yet.</div>
      )}

      {departments.length > 0 && (
        <div className={styles.tileGrid}>
          {departments.map((dept) => (
            <div className={styles.tile} key={dept.department}>
              <div className={styles.tileHeader}>
                <span className={styles.tileName}>{dept.department}</span>
              </div>
              <div style={{ marginTop: 10 }}>
                <div className={styles.tileMetric}>
                  <span>Employees</span>
                  <span className={styles.tileMetricValue}>{dept.employee_count}</span>
                </div>
                <div className={styles.tileMetric}>
                  <span>Open alerts</span>
                  <span className={styles.tileMetricValue} style={dept.open_alerts > 0 ? { color: "#F2A93B" } : {}}>
                    {dept.open_alerts}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
