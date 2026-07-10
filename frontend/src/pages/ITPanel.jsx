// IT Panel - Section 7: sees device/system health only, never employee
// identity tied to positions (device IDs only).
import { useDeviceHealth } from "../hooks/useDeviceHealth";
import styles from "./OpsPanel.module.css";

const STALE_AFTER_MS = 60_000; // placeholder - real beacon ping interval should inform this
const OFFLINE_AFTER_MS = 300_000;

function freshness(lastSeenAt) {
  if (!lastSeenAt) return "offline";
  const ageMs = Date.now() - new Date(lastSeenAt).getTime();
  if (ageMs > OFFLINE_AFTER_MS) return "offline";
  if (ageMs > STALE_AFTER_MS) return "warn";
  return "ok";
}

function batteryClass(pct) {
  if (pct == null) return "";
  if (pct < 20) return "critical";
  if (pct < 40) return "warn";
  return "ok";
}

export default function ITPanel() {
  const { devices, loading, error } = useDeviceHealth();

  const online = devices.filter((d) => freshness(d.last_seen_at) === "ok").length;
  const lowBattery = devices.filter((d) => d.battery_pct != null && d.battery_pct < 20).length;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>IT panel</h1>
        <p className={styles.subtitle}>
          Beacon/gateway health, tag battery status, system uptime, network diagnostics.
        </p>
      </div>

      <div className={styles.summaryRow}>
        <div className={styles.summaryCard}>
          <div className={styles.summaryLabel}>Devices online</div>
          <div className={`${styles.summaryValue} ${styles.ok}`}>{online}</div>
        </div>
        <div className={styles.summaryCard}>
          <div className={styles.summaryLabel}>Total devices</div>
          <div className={styles.summaryValue}>{devices.length}</div>
        </div>
        <div className={styles.summaryCard}>
          <div className={styles.summaryLabel}>Low battery (&lt;20%)</div>
          <div className={`${styles.summaryValue} ${lowBattery > 0 ? styles.critical : styles.ok}`}>
            {lowBattery}
          </div>
        </div>
      </div>

      {error && (
        <div className={styles.errorBanner}>
          Couldn't load device health: {error}
        </div>
      )}

      {loading && devices.length === 0 && !error && (
        <div className={styles.emptyState}>Loading device health…</div>
      )}

      {!loading && devices.length === 0 && !error && (
        <div className={styles.emptyState}>No devices reporting yet.</div>
      )}

      {devices.length > 0 && (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Status</th>
              <th>Tag</th>
              <th>Battery</th>
              <th>Last seen</th>
              <th>Zone</th>
            </tr>
          </thead>
          <tbody>
            {devices.map((d) => {
              const fresh = freshness(d.last_seen_at);
              return (
                <tr key={d.tag_id ?? d.tag_uid}>
                  <td>
                    <span className={`${styles.statusDot} ${styles[fresh]}`} />
                    {fresh === "ok" ? "Online" : fresh === "warn" ? "Stale" : "Offline"}
                  </td>
                  <td className={styles.mono}>{d.tag_uid}</td>
                  <td className={`${styles.mono} ${styles[batteryClass(d.battery_pct)] ?? ""}`}>
                    {d.battery_pct != null ? `${d.battery_pct}%` : "—"}
                  </td>
                  <td className={styles.mono}>
                    {d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : "Never"}
                  </td>
                  <td>{d.zone_name ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
