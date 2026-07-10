// HR Panel - sees aggregated attendance/zone summaries only, never raw
// position coordinates or checkpoint photos (Section 7 data minimization).
import { useAttendanceSummary } from "../hooks/useAttendanceSummary";
import styles from "./OpsPanel.module.css";

// Deterministic color per zone name, so the same zone always gets the same
// color across every employee's bar without the backend needing to assign
// one. Palette deliberately distinct from the app's status colors
// (green/amber/red mean freshness/severity elsewhere - reusing them here
// for "which zone" would be a confusing collision of meaning).
const ZONE_PALETTE = ["#5B8DEF", "#9B6BD6", "#4FB8A8", "#D68B4F", "#7B879E"];

function zoneColor(zoneName) {
  let hash = 0;
  for (let i = 0; i < zoneName.length; i++) hash = (hash * 31 + zoneName.charCodeAt(i)) >>> 0;
  return ZONE_PALETTE[hash % ZONE_PALETTE.length];
}

function ShiftBar({ breakdown, totalMinutes }) {
  if (!totalMinutes) return <div className={styles.emptyState}>No activity</div>;
  return (
    <div className={styles.shiftBar}>
      {breakdown.map((seg) => (
        <div
          key={seg.zone_name}
          className={styles.shiftBarSegment}
          style={{
            width: `${(seg.minutes / totalMinutes) * 100}%`,
            background: zoneColor(seg.zone_name),
          }}
          title={`${seg.zone_name}: ${seg.minutes}m`}
        />
      ))}
    </div>
  );
}

export default function HRPanel() {
  const { employees, loading, error } = useAttendanceSummary();

  const allZones = [...new Set(employees.flatMap((e) => e.zone_breakdown?.map((z) => z.zone_name) ?? []))];
  const nonCompliant = employees.filter((e) => e.shift_compliant === false).length;

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
          <div className={styles.summaryLabel}>Employees tracked today</div>
          <div className={styles.summaryValue}>{employees.length}</div>
        </div>
        <div className={styles.summaryCard}>
          <div className={styles.summaryLabel}>Shift compliance issues</div>
          <div className={`${styles.summaryValue} ${nonCompliant > 0 ? styles.warn : styles.ok}`}>
            {nonCompliant}
          </div>
        </div>
      </div>

      {error && (
        <div className={styles.errorBanner}>
          Couldn't load attendance summary: {error}
        </div>
      )}

      {loading && employees.length === 0 && !error && (
        <div className={styles.emptyState}>Loading attendance summary…</div>
      )}

      {!loading && employees.length === 0 && !error && (
        <div className={styles.emptyState}>No attendance data yet.</div>
      )}

      {employees.length > 0 && (
        <>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Employee</th>
                <th>Zone time breakdown</th>
                <th>Total time</th>
                <th>Shift compliance</th>
              </tr>
            </thead>
            <tbody>
              {employees.map((e) => (
                <tr key={e.employee_id}>
                  <td>{e.employee_name}</td>
                  <td>
                    <ShiftBar breakdown={e.zone_breakdown ?? []} totalMinutes={e.total_minutes} />
                  </td>
                  <td className={styles.mono}>{e.total_minutes ? `${Math.round(e.total_minutes / 60)}h ${e.total_minutes % 60}m` : "—"}</td>
                  <td>
                    <span className={`${styles.statusDot} ${e.shift_compliant === false ? styles.warn : styles.ok}`} />
                    {e.shift_compliant === false ? "Review" : "On track"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {allZones.length > 0 && (
            <div className={styles.shiftBarLegend}>
              {allZones.map((zone) => (
                <span key={zone}>
                  <span className={styles.shiftBarLegendSwatch} style={{ background: zoneColor(zone) }} />
                  {zone}
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
